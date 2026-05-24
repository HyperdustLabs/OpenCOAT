"""In-process JSON-RPC 2.0 dispatcher over :class:`OpenCOATRuntime` (M4 PR-18).

Pure request/response mapping — no sockets, no HTTP. The daemon's
:class:`~opencoat_runtime_daemon.ipc.http_server.HttpServer` (PR-19) parses
HTTP POST bodies, calls :meth:`JsonRpcHandler.handle`, and maps the
returned dict to JSON (or ``204`` when the handler returns ``None`` for
a notification).

Methods are dotted names grouped by domain:

``joinpoint.submit``
    Params: ``{"joinpoint": <JoinpointEvent wire>, "return_none_when_empty"?: bool, "context"?: object, "extract_from_chat"?: bool}``
    When ``extract_from_chat`` is true (or ``runtime.joinpoint_automation.extract_from_user_message``
    is enabled), mines user chat from the joinpoint payload via ``concern.extract`` before weaving.
    Result: ``ConcernInjection`` wire object or ``null``.

``concern.list`` / ``concern.get`` / ``concern.upsert`` / ``concern.delete``
    Thin wrappers around :class:`~opencoat_runtime_core.ports.ConcernStore`.

``concern.extract``
    Params: ``{"text": str, "origin": str, "ref"?: str, "dry_run"?: bool}``.
    Wraps :class:`~opencoat_runtime_core.concern.ConcernExtractor` over the
    LLM the runtime is wired with (``runtime.llm``). Returns ``{"candidates":
    [...Concern], "rejected": [{"span": str, "reason": str}]}``. When
    ``dry_run=false`` (the default) the dispatcher additionally upserts
    every candidate into ``runtime.concern_store`` so the host can
    "extract → use" in a single round trip; pass ``dry_run=true`` to
    inspect what *would* be extracted without touching the store.
    ``origin`` must be one of
    :meth:`ConcernExtractor.supported_origins`; anything else maps to
    JSON-RPC ``-32602``. M5 PR-48.

``runtime.snapshot`` / ``runtime.current_vector`` / ``runtime.last_injection``
    Introspection helpers for health checks and the CLI.

``runtime.llm_info``
    Surface the LLM the daemon ended up wired with (label, kind, real-
    or-stub flag, plus an optional fix-it hint when degraded). Lets
    CLI commands like ``opencoat concern extract`` warn loudly when
    the daemon is on stub-fallback instead of silently returning
    empty results.

``dcn.activation_log``
    Params: ``{"concern_id"?: str, "limit"?: int}`` — forwards to
    :meth:`~opencoat_runtime_core.ports.DCNStore.activation_log`.

``reflex.policies.export``
    Params: ``{"action_kind"?: "tool_call"}``. Returns portable deterministic
    policy specs for the bridge in-proc ``ReflexMonitor`` (v0.3 §10.4).

``health.ping``
    Result: ``{"ok": true}`` — proves the handler is wired without
    touching stores.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.concern import ConcernBuilder, ConcernExtractor
from opencoat_runtime_core.concern.chat_extract import chat_text_for_extraction
from opencoat_runtime_core.concern.reflex_policy_export import export_reflex_policies
from opencoat_runtime_protocol import Concern, ConcernInjection, JoinpointEvent
from pydantic import ValidationError

from ..runtime_builder import LLMInfo

# JSON-RPC 2.0 error codes (subset we use today).
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


class JsonRpcParamsError(ValueError):
    """Invalid params for a known method — maps to JSON-RPC -32602."""


def _expect_params_dict(params: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(params, list):
        raise JsonRpcParamsError("this method expects a params object, not an array")
    return params


def _json_safe(obj: Any) -> Any:
    """Recursively coerce datetimes and Pydantic models for JSON encoding."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, Concern | JoinpointEvent | ConcernInjection):
        return obj.model_dump(mode="json")
    md = getattr(obj, "model_dump", None)
    if callable(md):
        return _json_safe(md(mode="json"))
    try:
        return _json_safe(asdict(obj))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(obj)


def _success_response(req_id: Any, result: Any) -> dict[str, Any]:
    # JSON-RPC 2.0 §5: Response objects MUST contain an ``id`` member
    # — the request's id verbatim, or ``null`` if the server couldn't
    # detect it (e.g. parse / invalid-request errors before id was
    # readable). Notifications (request without an ``id`` member) get
    # *no* response at all, which is the caller's responsibility.
    return {"jsonrpc": "2.0", "result": _json_safe(result), "id": req_id}


def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": req_id,
    }


# Sentinel returned by ``runtime.llm_info`` when the dispatcher was
# constructed without an explicit ``llm_info=`` argument — i.e. an
# in-test or embedded caller that doesn't go through the daemon
# bootstrap. Marked ``real=False`` so CLI / banner branches that
# refuse to proceed on stub still fire; ``kind="unknown"`` keeps
# code that *does* care about provider distinct from a deliberate
# ``provider: stub`` choice.
_UNKNOWN_LLM_INFO = LLMInfo(
    label="unknown",
    kind="unknown",
    real=False,
    requested="unknown",
    hint=(
        "JsonRpcHandler was constructed without llm_info — the LLM "
        "the handler is actually talking to is not introspectable. "
        "Expected only in tests / embedded callers."
    ),
)


class JsonRpcHandler:
    """Dispatch JSON-RPC requests against a live :class:`OpenCOATRuntime`."""

    def __init__(
        self,
        runtime: OpenCOATRuntime,
        *,
        llm_info: LLMInfo | None = None,
    ) -> None:
        self._rt = runtime
        self._llm_info = llm_info if llm_info is not None else _UNKNOWN_LLM_INFO
        # ConcernExtractor is built lazily so the dispatcher pays the
        # construction cost only when a host actually calls
        # ``concern.extract`` (most daemons do nothing but
        # ``joinpoint.submit`` for hours at a stretch).
        self._extractor: ConcernExtractor | None = None
        self._methods: dict[str, Any] = {
            "health.ping": self._health_ping,
            "joinpoint.submit": self._joinpoint_submit,
            "concern.list": self._concern_list,
            "concern.get": self._concern_get,
            "concern.upsert": self._concern_upsert,
            "concern.delete": self._concern_delete,
            "concern.extract": self._concern_extract,
            "runtime.snapshot": self._runtime_snapshot,
            "runtime.current_vector": self._runtime_current_vector,
            "runtime.last_injection": self._runtime_last_injection,
            "runtime.llm_info": self._runtime_llm_info,
            "dcn.activation_log": self._dcn_activation_log,
            "reflex.policies.export": self._reflex_policies_export,
        }

    def handle(self, message: str | dict[str, Any]) -> dict[str, Any] | None:
        """Parse ``message``, dispatch, and return a JSON-RPC response dict.

        Returns ``None`` when the request is a **valid** notification
        — a well-formed Request object with no ``id`` member, per
        JSON-RPC 2.0 §4.1. :class:`~opencoat_runtime_daemon.ipc.http_server.HttpServer`
        maps ``None`` to ``204 No Content`` with an empty body.

        Envelope errors (parse failures, wrong ``jsonrpc`` version, bad
        ``method`` / ``params`` shape) *always* yield a response with
        ``id: null`` — only *valid* Request objects without ``id`` are
        notifications (Codex P2 on PR-19). Otherwise a malformed
        payload that happens to omit ``id`` would silently disappear
        instead of returning ``-32600`` / ``-32602``.
        """
        try:
            req = json.loads(message) if isinstance(message, str) else dict(message)
        except (TypeError, json.JSONDecodeError) as exc:
            # Parse error: id was never readable, spec says reply with id=null.
            return _error_response(None, _PARSE_ERROR, f"Parse error: {exc}")

        if not isinstance(req, dict):
            return _error_response(None, _INVALID_REQUEST, "Request must be a JSON object")

        req_id = req.get("id")  # may legitimately be null in the request

        # --- Envelope validation: errors here ALWAYS get a response, ---
        # --- because we cannot trust an invalid Request to be a   ---
        # --- notification. Use req_id (which is None if omitted). ---
        if req.get("jsonrpc") != "2.0":
            return _error_response(req_id, _INVALID_REQUEST, "jsonrpc must be '2.0'")

        method = req.get("method")
        if not isinstance(method, str) or not method:
            return _error_response(req_id, _INVALID_REQUEST, "method must be a non-empty string")

        raw_params = req.get("params")
        if raw_params is not None and not isinstance(raw_params, (dict, list)):
            return _error_response(req_id, _INVALID_PARAMS, "params must be object, array, or null")

        # Envelope is well-formed → from here on, an omitted id makes
        # this a JSON-RPC notification and we must NOT respond, even
        # on unknown method / handler errors (§4.1).
        is_notification = "id" not in req

        def _maybe(resp: dict[str, Any]) -> dict[str, Any] | None:
            return None if is_notification else resp

        handler = self._methods.get(method)
        if handler is None:
            return _maybe(_error_response(req_id, _METHOD_NOT_FOUND, f"Unknown method: {method!r}"))

        params_obj: dict[str, Any] | list[Any] = {} if raw_params is None else raw_params

        try:
            result = handler(params_obj)
        except JsonRpcParamsError as exc:
            return _maybe(_error_response(req_id, _INVALID_PARAMS, str(exc)))
        except ValidationError as exc:
            # Codex P2 on PR-18: schema validation failures are *client*
            # input bugs, not server faults. Surface them as -32602
            # so callers can fix the payload instead of paging on-call.
            return _maybe(_error_response(req_id, _INVALID_PARAMS, f"validation error: {exc}"))
        except Exception as exc:
            return _maybe(_error_response(req_id, _INTERNAL_ERROR, str(exc)))

        return _maybe(_success_response(req_id, result))

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------

    @staticmethod
    def _health_ping(_params: dict[str, Any] | list[Any]) -> dict[str, bool]:
        return {"ok": True}

    def _joinpoint_submit(self, params: dict[str, Any] | list[Any]) -> Any:
        p = _expect_params_dict(params)
        raw = p.get("joinpoint")
        if not isinstance(raw, dict):
            raise JsonRpcParamsError("joinpoint must be an object")
        jp = JoinpointEvent.model_validate(raw)
        ret_none = bool(p.get("return_none_when_empty", False))
        ctx = p.get("context")
        context = ctx if isinstance(ctx, dict) else None
        extract_flag = p.get("extract_from_chat", False)
        if not isinstance(extract_flag, bool):
            raise JsonRpcParamsError("extract_from_chat must be a boolean when provided")
        self._maybe_extract_from_joinpoint(jp, force=extract_flag)
        inj = self._rt.on_joinpoint(jp, context=context, return_none_when_empty=ret_none)
        return None if inj is None else inj.model_dump(mode="json")

    def _maybe_extract_from_joinpoint(self, jp: JoinpointEvent, *, force: bool) -> int:
        """Mine user chat into the concern store. Returns number of concerns upserted."""
        automation = self._rt.config.joinpoint_automation
        if not force and not automation.extract_from_user_message:
            return 0
        text = chat_text_for_extraction(jp)
        min_chars = automation.extract_min_message_chars
        if not text or len(text) < min_chars:
            return 0
        if self._extractor is None:
            self._extractor = ConcernExtractor(llm=self._rt.llm)
        ref = jp.agent_session_id or jp.host_round_id or jp.id
        result = self._extractor.extract(text, origin="user_input", ref=ref)
        if not result.candidates:
            return 0
        builder = ConcernBuilder(store=self._rt.concern_store)
        built = builder.build_many(list(result.candidates))
        return len(built)

    def _concern_list(self, params: dict[str, Any] | list[Any]) -> list[Any]:
        p = _expect_params_dict(params)
        allowed = ("kind", "tag", "lifecycle_state", "limit")
        kwargs: dict[str, Any] = {k: p[k] for k in allowed if k in p}
        concerns = self._rt.concern_store.list(**kwargs)
        return [c.model_dump(mode="json") for c in concerns]

    def _concern_get(self, params: dict[str, Any] | list[Any]) -> Any:
        p = _expect_params_dict(params)
        cid = p.get("concern_id")
        if not isinstance(cid, str) or not cid:
            raise JsonRpcParamsError("concern_id must be a non-empty string")
        c = self._rt.concern_store.get(cid)
        return None if c is None else c.model_dump(mode="json")

    def _concern_upsert(self, params: dict[str, Any] | list[Any]) -> Any:
        p = _expect_params_dict(params)
        raw = p.get("concern")
        if not isinstance(raw, dict):
            raise JsonRpcParamsError("concern must be an object")
        c = Concern.model_validate(raw)
        out = self._rt.concern_store.upsert(c)
        return out.model_dump(mode="json")

    def _concern_delete(self, params: dict[str, Any] | list[Any]) -> None:
        p = _expect_params_dict(params)
        cid = p.get("concern_id")
        if not isinstance(cid, str) or not cid:
            raise JsonRpcParamsError("concern_id must be a non-empty string")
        self._rt.concern_store.delete(cid)

    def _concern_extract(self, params: dict[str, Any] | list[Any]) -> dict[str, Any]:
        """``concern.extract`` — host-driven dynamic concern creation (M5 PR-48).

        Plumbs natural-language text through
        :class:`~opencoat_runtime_core.concern.ConcernExtractor` and, by
        default, upserts every produced candidate into the runtime's
        :class:`~opencoat_runtime_core.ports.ConcernStore` — so a host
        can collapse "extract candidates from what the user just said"
        and "have them visible to the next ``joinpoint.submit``" into
        one round trip. ``dry_run=true`` skips the upsert step (useful
        for previews / CLI ``--dry-run``).

        Rejections are passed through verbatim so the host can surface
        them as warnings (LLM error, schema validation failure, …)
        instead of silently swallowing failed spans.
        """
        p = _expect_params_dict(params)

        text = p.get("text")
        if not isinstance(text, str) or not text.strip():
            raise JsonRpcParamsError("text must be a non-empty string")

        origin = p.get("origin")
        if not isinstance(origin, str) or not origin:
            raise JsonRpcParamsError("origin must be a non-empty string")
        if origin not in ConcernExtractor.supported_origins():
            allowed = ", ".join(ConcernExtractor.supported_origins())
            raise JsonRpcParamsError(f"unsupported origin {origin!r}; expected one of: {allowed}")

        ref = p.get("ref")
        if ref is not None and not isinstance(ref, str):
            raise JsonRpcParamsError("ref must be a string when provided")

        dry_run = p.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise JsonRpcParamsError("dry_run must be a boolean when provided")

        if self._extractor is None:
            self._extractor = ConcernExtractor(llm=self._rt.llm)

        result = self._extractor.extract(text, origin=origin, ref=ref)

        builder = ConcernBuilder(store=self._rt.concern_store)
        if dry_run:
            built = [builder.enrich(c) for c in result.candidates]
        else:
            built = builder.build_many(list(result.candidates))

        return {
            "candidates": [c.model_dump(mode="json") for c in built],
            "rejected": [{"span": r.span, "reason": r.reason} for r in result.rejected],
            "upserted": not dry_run,
        }

    def _runtime_snapshot(self, _params: dict[str, Any] | list[Any]) -> Any:
        return self._rt.snapshot()

    def _runtime_current_vector(self, _params: dict[str, Any] | list[Any]) -> Any:
        v = self._rt.current_vector()
        return None if v is None else v.model_dump(mode="json")

    def _runtime_last_injection(self, _params: dict[str, Any] | list[Any]) -> Any:
        inj = self._rt.last_injection()
        return None if inj is None else inj.model_dump(mode="json")

    def _runtime_llm_info(self, _params: dict[str, Any] | list[Any]) -> dict[str, Any]:
        """Surface the resolved LLM provider so the CLI / banner can warn.

        Stable wire shape so external dashboards can also poll this:

        ``label``    Human-friendly identifier (``"openai/gpt-4o-mini"``).
        ``kind``     Coarse provider class: ``"openai" | "anthropic" |
                     "azure" | "stub" | "unknown"`` — branch on this
                     instead of parsing ``label``.
        ``real``     ``True`` iff a real provider is wired.
        ``requested``The provider value the daemon config asked for —
                     ``"auto"`` when auto-detection chose ``kind``.
        ``hint``     Empty string on the happy path; otherwise a short
                     fix-it line callers should surface verbatim.
        """
        info = self._llm_info
        return {
            "label": info.label,
            "kind": info.kind,
            "real": info.real,
            "requested": info.requested,
            "hint": info.hint,
        }

    def _dcn_activation_log(self, params: dict[str, Any] | list[Any]) -> list[Any]:
        p = _expect_params_dict(params)
        cid = p.get("concern_id")
        concern_id = cid if isinstance(cid, str) else None
        limit = p.get("limit")
        lim = int(limit) if isinstance(limit, int) else None
        rows = self._rt.dcn_store.activation_log(concern_id, limit=lim)
        return [dict(r) for r in rows]

    def _reflex_policies_export(self, params: dict[str, Any] | list[Any]) -> dict[str, Any]:
        """Portable deterministic reflex specs for in-proc bridge ``ReflexMonitor``."""
        p = _expect_params_dict(params)
        action_kind = p.get("action_kind", "tool_call")
        if action_kind not in ("tool_call",):
            raise JsonRpcParamsError("action_kind must be 'tool_call'")
        concerns = self._rt.concern_store.list()
        return export_reflex_policies(concerns, action_kind=action_kind)


__all__ = ["JsonRpcHandler", "JsonRpcParamsError"]
