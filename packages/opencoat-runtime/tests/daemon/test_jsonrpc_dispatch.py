"""Tests for :class:`~opencoat_runtime_daemon.ipc.jsonrpc_dispatch.JsonRpcHandler` (M4 PR-18)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_daemon import LLMInfo, build_runtime
from opencoat_runtime_daemon.config import load_config
from opencoat_runtime_daemon.ipc.jsonrpc_dispatch import JsonRpcHandler
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    JoinpointEvent,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _concern(cid: str = "c-rpc") -> Concern:
    return Concern(
        id=cid,
        name="RPC smoke",
        description="d",
        pointcut=Pointcut(match=PointcutMatch(any_keywords=["refund"])),
        advice=Advice(type=AdviceType.REASONING_GUIDANCE, content="x"),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.PROMPT_LEVEL,
            target="reasoning.hints",
            priority=0.5,
        ),
    )


def _jp() -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-rpc",
        level=2,
        name="before_response",
        host="jsonrpc-test",
        agent_session_id="s",
        ts=datetime(2026, 5, 11, 14, 0, tzinfo=UTC),
        payload={"text": "refund", "raw_text": "refund"},
    )


@pytest.fixture
def handler() -> JsonRpcHandler:
    with build_runtime(load_config(), env={}) as built:
        yield JsonRpcHandler(built.runtime, llm_info=built.llm_info)


def _req(method: str, params: object | None = None, *, req_id: object = 1) -> dict:
    d: dict = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params is not None:
        d["params"] = params
    return d


class TestEnvelope:
    def test_parse_error(self, handler: JsonRpcHandler) -> None:
        out = handler.handle("{")
        assert out["error"]["code"] == -32700

    def test_invalid_not_object(self, handler: JsonRpcHandler) -> None:
        out = handler.handle("[1,2,3]")
        assert out["error"]["code"] == -32600

    def test_method_not_found(self, handler: JsonRpcHandler) -> None:
        out = handler.handle(_req("nope.missing"))
        assert out["error"]["code"] == -32601

    def test_bad_jsonrpc_version(self, handler: JsonRpcHandler) -> None:
        out = handler.handle({"jsonrpc": "1.0", "method": "health.ping", "id": 1})
        assert out["error"]["code"] == -32600


class TestMethods:
    def test_health_ping(self, handler: JsonRpcHandler) -> None:
        out = handler.handle(_req("health.ping"))
        assert out == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}

    def test_round_trip_via_json_string(self, handler: JsonRpcHandler) -> None:
        c = _concern()
        h = handler
        up = h.handle(json.dumps(_req("concern.upsert", {"concern": c.model_dump(mode="json")})))
        assert "error" not in up
        assert up["result"]["id"] == "c-rpc"

        got = h.handle(json.dumps(_req("concern.get", {"concern_id": "c-rpc"})))
        assert got["result"]["id"] == "c-rpc"

        inj = h.handle(
            json.dumps(
                _req(
                    "joinpoint.submit",
                    {"joinpoint": _jp().model_dump(mode="json")},
                )
            )
        )
        assert "error" not in inj
        assert inj["result"] is not None
        assert any(x["concern_id"] == "c-rpc" for x in inj["result"]["injections"])

        snap = h.handle(_req("runtime.snapshot"))
        assert snap["result"]["concern_count"] >= 1

        h.handle(_req("concern.delete", {"concern_id": "c-rpc"}))
        gone = h.handle(_req("concern.get", {"concern_id": "c-rpc"}))
        assert gone["result"] is None

    def test_invalid_joinpoint_params(self, handler: JsonRpcHandler) -> None:
        out = handler.handle(_req("joinpoint.submit", {}))
        assert out["error"]["code"] == -32602

    def test_activation_log_empty(self, handler: JsonRpcHandler) -> None:
        out = handler.handle(_req("dcn.activation_log", {}))
        assert out["result"] == []


class TestJsonRpcCompliance:
    """Codex P2 on PR-18: response id + validation error mapping."""

    def test_validation_error_maps_to_invalid_params(self, handler: JsonRpcHandler) -> None:
        # ``joinpoint`` is shaped right but fails Pydantic validation
        # (missing required fields). Must be -32602, not -32603.
        out = handler.handle(
            _req("joinpoint.submit", {"joinpoint": {"id": "jp-bad"}}),
        )
        assert out is not None
        assert out["error"]["code"] == -32602
        assert "validation" in out["error"]["message"].lower()

    def test_concern_upsert_validation_error_is_invalid_params(
        self, handler: JsonRpcHandler
    ) -> None:
        out = handler.handle(_req("concern.upsert", {"concern": {"id": "broken"}}))
        assert out is not None
        assert out["error"]["code"] == -32602

    def test_notification_returns_none(self, handler: JsonRpcHandler) -> None:
        # JSON-RPC 2.0 §4.1: request without "id" is a notification;
        # server MUST NOT reply. We return None so the HTTP layer can
        # translate that into 204/no body.
        assert handler.handle({"jsonrpc": "2.0", "method": "health.ping"}) is None

    def test_notification_with_invalid_method_still_returns_none(
        self, handler: JsonRpcHandler
    ) -> None:
        assert handler.handle({"jsonrpc": "2.0", "method": "nope.bad"}) is None

    def test_response_always_contains_id_member(self, handler: JsonRpcHandler) -> None:
        out = handler.handle(_req("health.ping", req_id=42))
        assert out is not None
        assert "id" in out and out["id"] == 42

    def test_explicit_null_id_is_a_real_request_not_a_notification(
        self, handler: JsonRpcHandler
    ) -> None:
        # JSON-RPC 2.0: ``"id": null`` is a real request; the
        # response must echo it back. Only an *omitted* id makes
        # the message a notification.
        out = handler.handle({"jsonrpc": "2.0", "method": "health.ping", "id": None})
        assert out is not None
        assert out["id"] is None
        assert out["result"] == {"ok": True}

    def test_parse_error_response_has_id_null(self, handler: JsonRpcHandler) -> None:
        out = handler.handle("not json")
        assert out is not None
        assert out["error"]["code"] == -32700
        assert out["id"] is None


class TestInvalidEnvelopeStillResponds:
    """Codex P2 on PR-19: invalid Request objects without ``id`` must
    still receive an error response with ``id: null`` — only *valid*
    Request objects without ``id`` are JSON-RPC notifications (§4.1).
    """

    def test_bad_jsonrpc_version_without_id_returns_error(self, handler: JsonRpcHandler) -> None:
        out = handler.handle({"jsonrpc": "1.0", "method": "health.ping"})
        assert out is not None
        assert out["error"]["code"] == -32600
        assert out["id"] is None

    def test_method_not_string_without_id_returns_error(self, handler: JsonRpcHandler) -> None:
        out = handler.handle({"jsonrpc": "2.0", "method": 1})
        assert out is not None
        assert out["error"]["code"] == -32600
        assert out["id"] is None

    def test_missing_method_without_id_returns_error(self, handler: JsonRpcHandler) -> None:
        out = handler.handle({"jsonrpc": "2.0"})
        assert out is not None
        assert out["error"]["code"] == -32600
        assert out["id"] is None

    def test_bad_params_type_without_id_returns_error(self, handler: JsonRpcHandler) -> None:
        out = handler.handle({"jsonrpc": "2.0", "method": "health.ping", "params": "hello"})
        assert out is not None
        assert out["error"]["code"] == -32602
        assert out["id"] is None

    def test_unknown_method_with_id_still_returns_error(self, handler: JsonRpcHandler) -> None:
        # Sanity: well-formed envelope, unknown method, id present →
        # -32601 with that id (suppression only fires on notifications).
        out = handler.handle({"jsonrpc": "2.0", "method": "no.such.method", "id": 5})
        assert out is not None
        assert out["error"]["code"] == -32601
        assert out["id"] == 5


# ---------------------------------------------------------------------------
# concern.extract (M5 PR-48)
# ---------------------------------------------------------------------------


def _scripted_extract_handler(structured: dict[str, Any]) -> JsonRpcHandler:
    """Build a handler over a runtime whose LLM hands back ``structured``.

    The default :class:`StubLLMClient` returns ``{}`` on ``structured()``,
    which the extractor (correctly) reads as "no concern in this span".
    For ``concern.extract`` tests we need at least one real candidate
    coming back, so we plant a minimal valid emitted dict and let the
    extractor stamp provenance + run pydantic validation as usual.
    """
    llm = StubLLMClient(default_structured=structured)
    rt = OpenCOATRuntime(
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=llm,
    )
    return JsonRpcHandler(rt)


class TestConcernExtract:
    """``concern.extract`` — the wire entry point that wraps
    :class:`~opencoat_runtime_core.concern.ConcernExtractor`.

    These tests pin three things the host SDK and CLI will lean on:

    1. Param validation routes to JSON-RPC ``-32602`` (not -32603),
       including the "origin must be in the catalog" rule.
    2. The happy path returns ``{candidates: [...], rejected: [...],
       upserted: bool}`` and side-effects the concern store when
       ``dry_run=false``.
    3. ``dry_run=true`` produces the same candidate set without
       touching the store — so the CLI's ``--dry-run`` preview is
       safe to run repeatedly.
    """

    def test_missing_text_is_invalid_params(self) -> None:
        h = _scripted_extract_handler({})
        out = h.handle(_req("concern.extract", {"origin": "user_input"}))
        assert out["error"]["code"] == -32602
        assert "text" in out["error"]["message"]

    def test_blank_text_is_invalid_params(self) -> None:
        h = _scripted_extract_handler({})
        out = h.handle(_req("concern.extract", {"text": "   ", "origin": "user_input"}))
        assert out["error"]["code"] == -32602
        assert "text" in out["error"]["message"]

    def test_missing_origin_is_invalid_params(self) -> None:
        h = _scripted_extract_handler({})
        out = h.handle(_req("concern.extract", {"text": "hello"}))
        assert out["error"]["code"] == -32602
        assert "origin" in out["error"]["message"]

    def test_unsupported_origin_lists_allowed_set(self) -> None:
        h = _scripted_extract_handler({})
        out = h.handle(
            _req("concern.extract", {"text": "hello world long enough", "origin": "memory"})
        )
        assert out["error"]["code"] == -32602
        msg = out["error"]["message"]
        assert "memory" in msg
        # Surface the catalog so the user knows what to fix.
        assert "user_input" in msg
        assert "manual_import" in msg

    def test_ref_must_be_string_when_provided(self) -> None:
        h = _scripted_extract_handler({})
        out = h.handle(
            _req(
                "concern.extract",
                {
                    "text": "long enough text",
                    "origin": "user_input",
                    "ref": 17,
                },
            )
        )
        assert out["error"]["code"] == -32602
        assert "ref" in out["error"]["message"]

    def test_dry_run_must_be_bool(self) -> None:
        h = _scripted_extract_handler({})
        out = h.handle(
            _req(
                "concern.extract",
                {
                    "text": "long enough text",
                    "origin": "user_input",
                    "dry_run": "yes",
                },
            )
        )
        assert out["error"]["code"] == -32602
        assert "dry_run" in out["error"]["message"]

    def test_happy_path_returns_candidates_and_upserts(self) -> None:
        h = _scripted_extract_handler({"name": "be brief"})
        out = h.handle(
            _req(
                "concern.extract",
                {
                    "text": "Please keep every answer under three sentences.",
                    "origin": "user_input",
                    "ref": "prompt-42",
                },
            )
        )
        assert "error" not in out
        result = out["result"]
        assert result["upserted"] is True
        assert len(result["candidates"]) == 1
        c = result["candidates"][0]
        assert c["name"] == "be brief"
        assert c["source"]["origin"] == "user_input"
        assert c["source"]["ref"] == "prompt-42"
        assert c.get("pointcut") is not None
        assert c.get("advice") is not None
        assert c.get("weaving_policy") is not None
        # The candidate must now also be visible via concern.get.
        got = h.handle(_req("concern.get", {"concern_id": c["id"]}))
        assert got["result"] is not None
        assert got["result"]["name"] == "be brief"
        assert got["result"].get("pointcut") is not None

    def test_dry_run_skips_store_upsert(self) -> None:
        h = _scripted_extract_handler({"name": "be brief"})
        out = h.handle(
            _req(
                "concern.extract",
                {
                    "text": "Please keep every answer under three sentences.",
                    "origin": "user_input",
                    "dry_run": True,
                },
            )
        )
        assert out["result"]["upserted"] is False
        assert len(out["result"]["candidates"]) == 1
        cid = out["result"]["candidates"][0]["id"]
        # Store must be empty — dry_run is a contract.
        rows = h.handle(_req("concern.list", {})).get("result", [])
        assert all(c["id"] != cid for c in rows)

    def test_no_candidates_means_empty_dict_signal(self) -> None:
        # Default stub returns ``{}`` → extractor reads "no rule in
        # this span", silent skip, zero candidates, zero rejections.
        h = _scripted_extract_handler({})
        out = h.handle(
            _req(
                "concern.extract",
                {
                    "text": "Some innocuous prose that isn't a rule at all.",
                    "origin": "manual_import",
                },
            )
        )
        assert out["result"]["candidates"] == []
        assert out["result"]["rejected"] == []
        assert out["result"]["upserted"] is True  # nothing to upsert, but call did run

    def test_supported_origins_all_round_trip(self) -> None:
        # Every advertised origin must produce a valid response (not
        # a -32602). Use ``{}`` as the LLM reply so we don't pay
        # validation overhead — we only want the dispatch path
        # exercised.
        for origin in (
            "manual_import",
            "user_input",
            "tool_result",
            "draft_output",
            "feedback",
        ):
            h = _scripted_extract_handler({})
            out = h.handle(
                _req(
                    "concern.extract",
                    {
                        "text": "A long enough span of free text to pass the segmenter.",
                        "origin": origin,
                    },
                )
            )
            assert "error" not in out, (origin, out)


def _scripted_failure_handler(error: Exception) -> JsonRpcHandler:
    """Handler whose LLM ``.structured()`` raises ``error`` on every call.

    Used to pin the "LLM down → rejection, not -32603" contract: the
    extractor catches per-span LLM errors and surfaces them via
    ``ExtractionResult.rejected``. Bug regressions that let a raw
    exception escape would surface here as ``-32603`` instead of a
    rejection row.
    """

    class _ExplodingLLM:
        def structured(self, *_a: object, **_k: object) -> dict[str, Any]:
            raise error

        def complete(self, *_a: object, **_k: object) -> str:
            raise AssertionError("unexpected complete() call")

        def chat(self, *_a: object, **_k: object) -> str:
            raise AssertionError("unexpected chat() call")

        def score(self, *_a: object, **_k: object) -> float:
            raise AssertionError("unexpected score() call")

    rt = OpenCOATRuntime(
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=_ExplodingLLM(),  # type: ignore[arg-type]
    )
    return JsonRpcHandler(rt)


class TestConcernExtractLLMFailures:
    """If the LLM provider is unreachable / errors, the extractor must
    surface that as a per-span ``rejected`` row, not let a server
    exception escape as JSON-RPC ``-32603``. The host can then show
    "couldn't extract because LLM is down" instead of paging on-call.
    """

    def test_llm_runtime_error_lands_as_rejection(self) -> None:
        h = _scripted_failure_handler(RuntimeError("provider unreachable"))
        out = h.handle(
            _req(
                "concern.extract",
                {
                    "text": "Please always keep replies under 3 sentences.",
                    "origin": "user_input",
                },
            )
        )
        assert "error" not in out
        assert out["result"]["candidates"] == []
        assert len(out["result"]["rejected"]) == 1
        reason = out["result"]["rejected"][0]["reason"]
        assert "RuntimeError" in reason
        assert "provider unreachable" in reason


# ---------------------------------------------------------------------------
# runtime.llm_info  (release-readiness — surface real-vs-stub to callers)
# ---------------------------------------------------------------------------


class TestRuntimeLlmInfo:
    """``runtime.llm_info`` — the wire surface CLI / banner use to warn
    operators when the daemon ended up on stub-fallback.

    Pinned contracts:

    1. Shape is ``{label, kind, real, requested, hint}`` — every key
       always present so dashboards and the CLI don't need to guard
       against missing fields.
    2. With the default config + empty env we get ``stub-fallback``
       and a non-empty hint pointing at the env vars to set.
    3. With an explicit ``provider: stub`` we get plain ``stub`` and
       no hint (deliberate choice, no nag).
    4. Handlers built without an ``llm_info=`` kwarg fall back to the
       ``unknown`` sentinel rather than crashing — this is the path
       embedded tests / older callers take.
    """

    def test_shape_with_default_config_and_no_env(self, handler: JsonRpcHandler) -> None:
        out = handler.handle(_req("runtime.llm_info"))
        assert "error" not in out
        info = out["result"]
        assert set(info) == {"label", "kind", "real", "requested", "hint"}
        # Default config = ``provider: auto``; empty env → stub-fallback.
        assert info["label"] == "stub-fallback"
        assert info["kind"] == "stub"
        assert info["real"] is False
        assert info["requested"] == "auto"
        assert "OPENAI_API_KEY" in info["hint"]

    def test_explicit_stub_provider_no_hint(self) -> None:
        from opencoat_runtime_daemon.config.loader import LLMSettings

        cfg = load_config()
        cfg = cfg.model_copy(update={"llm": LLMSettings(provider="stub")})
        with build_runtime(cfg, env={}) as built:
            h = JsonRpcHandler(built.runtime, llm_info=built.llm_info)
            info = h.handle(_req("runtime.llm_info"))["result"]
        assert info["label"] == "stub"
        assert info["kind"] == "stub"
        assert info["real"] is False
        assert info["requested"] == "stub"
        # Deliberate stub choice → no nag.
        assert info["hint"] == ""

    def test_handler_without_llm_info_returns_unknown_sentinel(self) -> None:
        with build_runtime(load_config(), env={}) as built:
            h = JsonRpcHandler(built.runtime)  # no llm_info kwarg
        info = h.handle(_req("runtime.llm_info"))["result"]
        assert info["kind"] == "unknown"
        assert info["real"] is False
        assert "JsonRpcHandler" in info["hint"]

    def test_passes_real_provider_info_through(self) -> None:
        # The dispatcher must not lose info between build → handler.
        # We build with a synthetic real-provider LLMInfo and check
        # the wire surfaces it verbatim.
        with build_runtime(load_config(), env={}) as built:
            real = LLMInfo(
                label="openai/gpt-4o-mini",
                kind="openai",
                real=True,
                requested="auto",
                hint="",
            )
            h = JsonRpcHandler(built.runtime, llm_info=real)
        info = h.handle(_req("runtime.llm_info"))["result"]
        assert info == {
            "label": "openai/gpt-4o-mini",
            "kind": "openai",
            "real": True,
            "requested": "auto",
            "hint": "",
        }


class TestJoinpointExtractFromChat:
    def test_extract_from_chat_flag_upserts_concerns(self) -> None:
        llm = StubLLMClient(
            default_structured={
                "name": "NVDA until Wednesday",
                "description": "Track NVDA through Wednesday ET close.",
                "generated_type": "user_constraint",
            }
        )
        rt = OpenCOATRuntime(
            concern_store=MemoryConcernStore(),
            dcn_store=MemoryDCNStore(),
            llm=llm,
        )
        h = JsonRpcHandler(rt)
        jp = JoinpointEvent(
            id="jp-user",
            level=1,
            name="on_user_input",
            host="test",
            ts=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
            payload={
                "messages": [
                    {
                        "role": "user",
                        "content": "Will NVDA keep falling before Wednesday close?",
                    }
                ],
            },
        )
        out = h.handle(
            _req(
                "joinpoint.submit",
                {
                    "joinpoint": jp.model_dump(mode="json"),
                    "extract_from_chat": True,
                },
            )
        )
        assert "error" not in out
        listed = h.handle(_req("concern.list"))["result"]
        assert len(listed) >= 1


class TestReflexPoliciesExport:
    def test_exports_hard_tool_guard_block_policies(self) -> None:
        from opencoat_runtime_cli.demo_concerns import demo_concerns

        store = MemoryConcernStore()
        for c in demo_concerns():
            store.upsert(c)
        rt = OpenCOATRuntime(
            concern_store=store,
            dcn_store=MemoryDCNStore(),
            llm=StubLLMClient(),
        )
        h = JsonRpcHandler(rt)
        out = h.handle(_req("reflex.policies.export", {"action_kind": "tool_call"}))
        assert "error" not in out
        result = out["result"]
        assert result["version"] == "0.1"
        ids = [p["id"] for p in result["policies"]]
        assert "demo-tool-block" in ids
