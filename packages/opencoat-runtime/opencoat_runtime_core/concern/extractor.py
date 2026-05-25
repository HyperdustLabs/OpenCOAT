"""Concern Extractor — v0.1 §20.1 (M2 PR-10).

Turns natural-language inputs (governance documents, user input,
tool results, draft outputs, feedback) into candidate :class:`Concern`
envelopes that downstream stages
(:class:`ConcernSeparator` → :class:`ConcernBuilder` →
:class:`ConcernStore`) can normalise and persist.

Pipeline per call
-----------------

::

    text  ──► _segment_spans()         # paragraphs / numbered items / bullets
          ──► _extract_one(span)       # llm.structured(schema=LLM_SCHEMA)
          ──► _stamp(emitted, origin)  # provenance: origin / ref / ts / trust
          ──► Concern(**stamped)       # pydantic validation (envelope)
          ──► dedupe by (name, type)   # within this call only
          ──► ExtractionResult(candidates, rejected)

Design constraints
------------------
* **Port-only** — the extractor never imports a concrete LLM provider.
  Hosts wire any :class:`LLMClient` (OpenAI / Anthropic / Azure / Stub)
  at construction.
* **Robust over strict** — spans that fail at any stage (LLM error,
  empty response, schema-validation error, duplicate) go into
  :class:`ExtractionResult.rejected` with a short reason. A bad span
  never crashes the whole call.
* **Lean LLM contract** — we do **not** ask the model to fabricate the
  full :file:`concern.schema.json` (pointcut + advice + weaving + …).
  We hand it a focused subset (:attr:`ConcernExtractor.LLM_SCHEMA`)
  covering the bits that genuinely need natural-language understanding:
  ``name`` / ``description`` / ``generated_type`` / ``generated_tags``.
  ``scope`` is intentionally omitted from the wire schema: OpenAI
  ``json_schema`` with ``strict: true`` rejects nested objects whose
  ``required`` does not list every property when
  ``additionalProperties: false``. The wire schema also keeps
  top-level ``required`` empty so ``{}`` signals "no concern"; the
  :class:`~opencoat_runtime_llm.openai_client.OpenAILLMClient` adapter
  therefore passes ``strict: false`` while still using ``json_schema``.
  The :class:`ConcernBuilder` (PR-11+) and the weaver attach ``scope`` /
  pointcut / advice / lifecycle defaults later. Less surface = less hallucination.
* **Provenance is authoritative** — even if the model emits a
  ``source`` block, the extractor overwrites it. The host knows where
  the text came from; the model is just helping shape it.
* **Determinism** — the extractor itself is deterministic given a
  deterministic LLM (the M1 stub or a mock). IDs default to a stable
  hash of ``(origin, ref, name)`` so re-runs over the same source
  text produce the same id, which lets downstream stores idempotently
  upsert.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from opencoat_runtime_protocol import COPR, Concern

from ..ports import LLMClient

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rejection:
    """A span that did **not** become a Concern, with a short reason.

    ``span`` is truncated to keep error reports readable; the full
    text is recoverable from the host's source document.
    """

    span: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Outcome of one extraction call.

    Attributes
    ----------
    candidates:
        Validated :class:`Concern` envelopes, one per accepted span,
        in source order. Already de-duplicated within this call.
    rejected:
        Per-span :class:`Rejection`\\ s with the reason the span did
        not produce a Concern (LLM error, empty response, schema
        violation, duplicate, etc.). Hosts can log / surface these
        without losing turn progress.
    """

    candidates: tuple[Concern, ...] = ()
    rejected: tuple[Rejection, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:  # pragma: no cover — trivial
        return bool(self.candidates)

    def __len__(self) -> int:  # pragma: no cover — trivial
        return len(self.candidates)


# ---------------------------------------------------------------------------
# Constants — LLM contract
# ---------------------------------------------------------------------------


# Self-contained, strict-friendly subset of concern.schema.json.  The
# LLM only needs to fill in the shape-shifting fields; structural
# defaults come from the pydantic envelope when we instantiate
# ``Concern(**emitted)``.
#
# ``required`` is intentionally empty: every per-origin instruction
# tells the model to return ``{}`` when the span isn't a rule
# (front-matter, prose, an aside).  Strict-mode providers (OpenAI
# strict, Azure) reject responses that violate ``required``, so a
# ``required: ["name"]`` here would make the no-concern signal
# unreachable on the wire and push the model to fabricate concerns
# for non-rule spans (Codex P1 on PR-10).  Non-empty dicts that omit
# ``name`` are still rejected at envelope time by pydantic
# (``Concern.name: str = Field(min_length=1)``), so the wire-level
# loosening doesn't weaken the eventual envelope guarantees.
#
# Do **not** add optional nested objects here unless their nested
# ``required`` lists every property (OpenAI strict rejects otherwise).
_LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 200},
        "kind": {"type": "string", "enum": ["concern", "meta_concern"]},
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"type": "string", "maxLength": 2000},
        "generated_type": {"type": "string", "maxLength": 100},
        "generated_tags": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 60},
            "maxItems": 16,
        },
    },
}


# Trust scores per origin — used when the LLM omits ``source.trust``.
# These are conservative defaults the host can override post-extract.
_DEFAULT_TRUST_BY_ORIGIN: dict[str, float] = {
    "manual_import": 0.95,
    "host_explicit_plan": 0.9,
    "intent_alignment": 0.9,
    "system_default": 0.85,
    "user_input": 0.7,
    "tool_result": 0.6,
    "feedback": 0.55,
    "memory": 0.45,
    "draft_output": 0.4,
    "environment_event": 0.4,
    "derived": 0.5,
}


# Per-origin instructions handed to the model as the system message.
# Each one is short, declarative, and biases the model toward the
# semantics of that origin (governance text vs ad-hoc user prompt vs
# tool log).  All instructions share the same JSON-output contract,
# enforced by ``LLM_SCHEMA``.
_INSTRUCTION_GOVERNANCE = (
    "You are an extractor of governance Concerns from policy / "
    "code-of-conduct / role-play / safety documents. Read the input "
    "span verbatim and emit AT MOST ONE Concern that captures its "
    "intent. The Concern's ``name`` is a short title (≤ 80 chars) "
    "stating the rule. ``description`` paraphrases the rule in one "
    "or two sentences. ``generated_type`` is a snake_case category "
    "(e.g. ``safety_rule``, ``style_constraint``, ``role_persona``, "
    "``tool_policy``). ``generated_tags`` are 0–8 lowercase keywords. "
    "Obligations (MUST / SHALL / required / forbidden / must never / "
    "do not) are rules — emit a Concern unless the span is only a bare "
    "heading, boilerplate, or small talk with no requirement. "
    "If the span is not a rule (e.g. front-matter, prose, an aside), "
    "return an empty object. "
    "Never return {} when the span states a prohibition or duty the "
    "assistant must follow."
)
_INSTRUCTION_USER = (
    "Extract Concerns implied by the user's request. ``name`` "
    "captures what the user wants treated as a constraint. Use "
    "``generated_type`` to tag the kind (e.g. ``user_preference``, "
    "``user_constraint``, ``persona``). Treat explicit safety, "
    "privacy, security, or compliance requirements as constraints worth "
    "extracting, not as disposable chit-chat. Return an empty object "
    "only if the span is purely informational with no behavioural "
    "expectation. "
    "Never return {} when the span states a prohibition, duty, or "
    "constraint the assistant must honour."
)
_INSTRUCTION_TOOL = (
    "Extract Concerns implied by a tool result. ``generated_type`` "
    "is typically ``tool_signal`` or ``risk_indicator``. Capture "
    "facts the agent should not forget on this turn. Empty object "
    "for routine output."
)
_INSTRUCTION_DRAFT = (
    "Extract Concerns implied by the agent's own draft output — "
    "things the agent committed to and should remain consistent "
    "with. ``generated_type`` like ``self_commitment`` or "
    "``output_invariant``. Empty object for routine prose."
)
_INSTRUCTION_FEEDBACK = (
    "Extract Concerns implied by user / reviewer feedback. "
    "``generated_type`` like ``user_feedback`` or ``policy_update``. "
    "Empty object if feedback is unrelated to behaviour."
)
_INSTRUCTION_INTENT_ALIGNMENT = (
    "You extract host operating INTENT for downstream concern alignment — "
    "not safety refusals or anti-role-play rules. The span is a bootstrap / "
    "startup directive: how the runtime agent should understand its mission "
    "and behave on later turns. Emit AT MOST ONE Concern stating the "
    "positive intent to honour (persona, operating mode, mission). "
    "Paraphrase faithfully; do NOT invert startup identity lines into "
    "prohibitions like 'do not claim to be X' unless the span itself "
    "explicitly forbids something. ``generated_type``: ``persona``, "
    "``operating_mode``, ``mission``, or ``man_bootstrap``. "
    "``generated_tags``: 0–8 lowercase keywords from the intent. "
    "Return {} only for bare boilerplate with no behavioural intent."
)


# Boundaries for the cheap NL segmenter.  We intentionally stay
# regex-only: heavyweight NLP belongs in COPR span_segmenter (later
# milestone), not here.  This is enough to break governance docs into
# rule-shaped chunks.
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n+")
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*•]|(?:\(?\d+\)|\d+\.))\s+")


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class ConcernExtractor:
    """Turn natural-language inputs into candidate :class:`Concern`\\ s.

    The headline M2 entry point is :meth:`extract_from_governance_doc`,
    which takes an authoritative policy / role-play / safety document
    and emits one Concern per detectable rule. The four other entry
    points (``user_input`` / ``tool_result`` / ``draft_output`` /
    ``feedback``) cover the remaining v0.1 §20.1 sources and share the
    same internal pipeline — only the ``source.origin`` and the
    instruction handed to the model differ.

    Parameters
    ----------
    llm:
        Any :class:`LLMClient` — the runtime never imports a concrete
        provider. For tests, pass a mock or the ``StubLLMClient``;
        for production, an :class:`OpenAILLMClient` /
        :class:`AnthropicLLMClient` / :class:`AzureOpenAILLMClient`.
    max_concerns_per_call:
        Hard cap on candidates returned from a single call. Excess
        spans are silently skipped (not added to ``rejected``) once
        the cap is reached, so a runaway document can't blow the
        downstream coordinator's budget.
    min_span_chars:
        Spans shorter than this (after stripping) are dropped before
        the LLM is even called. Stops the model from being asked to
        extract a Concern from "yes." or "###".
    max_tokens_per_span:
        Forwarded to :meth:`LLMClient.structured` as the per-call
        token cap. ``None`` lets the upstream provider pick.
    now:
        Optional clock injected for deterministic tests. Defaults to
        ``datetime.now(UTC)``.
    """

    LLM_SCHEMA: dict[str, Any] = _LLM_SCHEMA

    def __init__(
        self,
        *,
        llm: LLMClient,
        max_concerns_per_call: int = 16,
        min_span_chars: int = 12,
        max_tokens_per_span: int | None = 512,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if max_concerns_per_call < 1:
            raise ValueError(f"max_concerns_per_call must be >= 1; got {max_concerns_per_call!r}")
        if min_span_chars < 1:
            raise ValueError(f"min_span_chars must be >= 1; got {min_span_chars!r}")
        self._llm = llm
        self._max_concerns_per_call = max_concerns_per_call
        self._min_span_chars = min_span_chars
        self._max_tokens_per_span = max_tokens_per_span
        self._now = now if now is not None else (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    # Canonical origin → (instruction, ref-needed?) table used by the
    # by-origin :meth:`extract` dispatcher. Each origin keeps the same
    # per-origin instruction the type-specific entry points use, so
    # going through ``extract(origin=…)`` produces byte-identical
    # output to calling ``extract_from_<origin>()`` directly. New
    # origins added in the future need only land an entry here and a
    # _DEFAULT_TRUST_BY_ORIGIN row.
    _ORIGIN_INSTRUCTIONS: ClassVar[dict[str, str]] = {
        "manual_import": _INSTRUCTION_GOVERNANCE,
        "intent_alignment": _INSTRUCTION_INTENT_ALIGNMENT,
        "user_input": _INSTRUCTION_USER,
        "tool_result": _INSTRUCTION_TOOL,
        "draft_output": _INSTRUCTION_DRAFT,
        "feedback": _INSTRUCTION_FEEDBACK,
    }

    @classmethod
    def supported_origins(cls) -> tuple[str, ...]:
        """Origins :meth:`extract` accepts, in catalog order.

        Stable wire surface for the daemon's ``concern.extract`` RPC
        and the ``opencoat concern extract --origin`` CLI: callers
        should refuse anything outside this tuple at the boundary
        rather than relying on the extractor to raise.
        """
        return tuple(cls._ORIGIN_INSTRUCTIONS)

    def extract(
        self,
        text: str,
        *,
        origin: str,
        ref: str | None = None,
    ) -> ExtractionResult:
        """Generic by-origin entry point — the one the RPC layer drives.

        ``origin`` selects the per-origin LLM instruction (governance
        text reads as authoritative policy, user input as constraint
        wishes, …) so the model's interpretation of the same span
        depends on where the host says it came from. The dispatch
        table is exposed via :meth:`supported_origins`.

        Equivalent to calling the type-specific
        ``extract_from_<origin>`` method with a string payload, with
        two narrow differences:

        * **``tool_result`` / ``feedback``** — the type-specific
          methods accept a structured ``dict`` and serialise it
          internally; here we take the *already-serialised* string
          so the wire stays flat (the host that knows the original
          dict shape is in a better position to format it). Pre-flatten
          via :func:`json.dumps` if you only have a dict.
        * The ``COPR``-derived ``ref`` of
          :meth:`extract_from_user_input` is replaced by the explicit
          ``ref`` kwarg, since by the time a request reaches the
          daemon the host typically doesn't ship the live COPR.

        Raises
        ------
        ValueError
            If ``origin`` is not in :meth:`supported_origins`.
        """
        instruction = self._ORIGIN_INSTRUCTIONS.get(origin)
        if instruction is None:
            allowed = ", ".join(self.supported_origins())
            raise ValueError(f"unsupported extract origin {origin!r}; expected one of: {allowed}")
        return self._extract(text, origin=origin, ref=ref, instruction=instruction)

    def extract_from_governance_doc(
        self,
        text: str,
        *,
        ref: str | None = None,
    ) -> ExtractionResult:
        """Headline M2 entry point: NL governance text → Concerns.

        Treats the input as authoritative policy text manually
        imported by the host. Each detected rule-shaped span emits at
        most one Concern.
        """
        return self._extract(
            text,
            origin="manual_import",
            ref=ref,
            instruction=_INSTRUCTION_GOVERNANCE,
        )

    def extract_for_intent_alignment(
        self,
        text: str,
        *,
        ref: str | None = None,
    ) -> ExtractionResult:
        """Bootstrap / startup text → one Concern capturing host operating intent.

        Unlike :meth:`extract_from_governance_doc`, the model is steered to
        align with the stated mission (persona / mode), not to refuse role-play.
        """
        return self._extract(
            text,
            origin="intent_alignment",
            ref=ref,
            instruction=_INSTRUCTION_INTENT_ALIGNMENT,
        )

    def extract_from_user_input(
        self,
        text: str,
        *,
        copr: COPR | None = None,
    ) -> ExtractionResult:
        """Mine Concerns from a user message / instruction."""
        ref = copr.prompt_id if copr is not None else None
        return self._extract(
            text,
            origin="user_input",
            ref=ref,
            instruction=_INSTRUCTION_USER,
        )

    def extract_from_tool_result(self, tool_name: str, result: dict[str, Any]) -> ExtractionResult:
        """Mine Concerns from a structured tool output."""
        text = _serialize_dict(result)
        return self._extract(
            text,
            origin="tool_result",
            ref=tool_name,
            instruction=_INSTRUCTION_TOOL,
        )

    def extract_from_draft_output(self, draft: str) -> ExtractionResult:
        """Mine Concerns the agent committed to in its own draft."""
        return self._extract(
            draft,
            origin="draft_output",
            ref=None,
            instruction=_INSTRUCTION_DRAFT,
        )

    def extract_from_feedback(self, feedback: dict[str, Any]) -> ExtractionResult:
        """Mine Concerns from user / reviewer feedback.

        Prefers ``feedback["text"]`` if present (the canonical free-
        text field); otherwise falls back to a JSON dump of the dict.
        ``feedback["source"]`` becomes the ``ref`` if set.
        """
        text_field = feedback.get("text")
        text = text_field if isinstance(text_field, str) else _serialize_dict(feedback)
        ref_field = feedback.get("source")
        ref = ref_field if isinstance(ref_field, str) else None
        return self._extract(
            text,
            origin="feedback",
            ref=ref,
            instruction=_INSTRUCTION_FEEDBACK,
        )

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _extract(
        self,
        text: str,
        *,
        origin: str,
        ref: str | None,
        instruction: str,
    ) -> ExtractionResult:
        spans = self._segment_spans(text)
        candidates: list[Concern] = []
        rejected: list[Rejection] = []
        seen_keys: set[tuple[str, str]] = set()

        for span in spans:
            if len(candidates) >= self._max_concerns_per_call:
                # Silent cap: the host already gets ``max_concerns_per_call``
                # candidates, which is plenty for one extraction call.
                # Adding "max reached" rejections would just create noise.
                break

            try:
                emitted = self._llm.structured(
                    messages=self._messages(instruction, span),
                    schema=self.LLM_SCHEMA,
                    max_tokens=self._max_tokens_per_span,
                    # Slightly above zero so small models (e.g. gpt-4o-mini)
                    # don't collapse to ``{}`` on every span while extraction
                    # remains near-deterministic.
                    temperature=0.15,
                )
            except Exception as exc:
                rejected.append(
                    Rejection(span=_short(span), reason=f"llm error: {type(exc).__name__}: {exc}")
                )
                continue

            if not isinstance(emitted, dict) or not emitted:
                # Empty dict is the "no concern in this span" signal in
                # all per-origin instructions — silent skip, not a
                # rejection.  A non-dict reply is a real bug.
                if not isinstance(emitted, dict):
                    rejected.append(
                        Rejection(
                            span=_short(span),
                            reason=f"llm returned {type(emitted).__name__}, expected dict",
                        )
                    )
                continue

            stamped = self._stamp(emitted, origin=origin, ref=ref)

            try:
                concern = Concern(**stamped)
            except Exception as exc:
                rejected.append(
                    Rejection(span=_short(span), reason=f"validation: {type(exc).__name__}: {exc}")
                )
                continue

            key = (concern.name.strip().lower(), (concern.generated_type or "").lower())
            if key in seen_keys:
                rejected.append(Rejection(span=_short(span), reason="duplicate"))
                continue
            seen_keys.add(key)
            candidates.append(concern)

        return ExtractionResult(candidates=tuple(candidates), rejected=tuple(rejected))

    def _segment_spans(self, text: str) -> list[str]:
        """Cheap NL segmenter: paragraphs + list items.

        1. Normalise CRLF / CR line endings to LF so Windows / old-Mac
           inputs behave the same as Unix ones (Codex P2 on PR-10:
           ``\\r\\n\\r\\n`` boundaries previously failed to match
           and collapsed multi-paragraph governance docs into a
           single span).
        2. Strip and collapse blank-line runs.
        3. Split by blank-line boundaries (paragraphs).
        4. Within each paragraph, also split before any line that
           starts with a list marker (``- ``, ``* ``, ``• ``,
           ``1.``, ``(2)``, …) so each rule in a numbered policy
           list becomes its own span.
        5. Drop spans shorter than ``min_span_chars`` after strip().

        The output is a list of de-whitespaced spans in source order.
        """
        if not text:
            return []
        normalised = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalised:
            return []
        paragraphs = _BLANK_LINE_RE.split(normalised)
        spans: list[str] = []
        for paragraph in paragraphs:
            for piece in _split_list_items(paragraph):
                stripped = piece.strip()
                if len(stripped) >= self._min_span_chars:
                    spans.append(stripped)
        return spans

    def _stamp(
        self,
        emitted: dict[str, Any],
        *,
        origin: str,
        ref: str | None,
    ) -> dict[str, Any]:
        """Inject provenance + envelope defaults into the LLM dict.

        We **overwrite** any ``source`` / ``id`` / ``kind`` /
        ``schema_version`` the model emitted, except: a non-empty
        ``id`` is kept (lets governance docs pin canonical ids
        in-text), and the source's ``trust`` falls back to the
        per-origin default if the model omitted it.
        """
        out: dict[str, Any] = {k: v for k, v in emitted.items() if k != "source"}
        out.setdefault("kind", "concern")
        out.setdefault("schema_version", "0.1.0")

        if not isinstance(out.get("name"), str) or not out["name"].strip():
            # Drop in an obviously invalid name so pydantic flags it
            # uniformly via the validation rejection path; we do NOT
            # fabricate a name from nowhere.
            return out

        if not isinstance(out.get("id"), str) or not out["id"].strip():
            out["id"] = self._mint_id(origin=origin, ref=ref, name=out["name"])

        out["source"] = {
            "origin": origin,
            "ref": ref,
            "ts": self._now().isoformat(),
            "trust": _DEFAULT_TRUST_BY_ORIGIN.get(origin, 0.5),
        }
        return out

    @staticmethod
    def _messages(instruction: str, span: str) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": instruction},
            {"role": "user", "content": span},
        ]

    @staticmethod
    def _mint_id(*, origin: str, ref: str | None, name: str) -> str:
        """Deterministic id from (origin, ref, name).

        SHA-1 truncated to 12 hex chars is plenty for collision
        avoidance within a single host's extraction stream and gives
        downstream stores stable upsert keys across re-runs.
        """
        seed = f"{origin}|{ref or ''}|{name.strip().lower()}"
        digest = hashlib.sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()
        return f"c-{digest[:12]}"


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _serialize_dict(payload: dict[str, Any]) -> str:
    """JSON-dump ``payload`` deterministically for the LLM.

    ``sort_keys=True`` keeps prompts stable across runs; ``ensure_ascii=False``
    preserves non-ASCII so policy text in any language survives the trip.
    Falls back to ``repr`` for objects that aren't JSON-encodable.
    """
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return repr(payload)


def _split_list_items(paragraph: str) -> list[str]:
    """Split a paragraph at list-marker boundaries.

    A leading marker on the very first line of a paragraph counts as
    a marker too; otherwise we'd glue the paragraph header to the
    first list item.
    """
    matches = list(_LIST_ITEM_RE.finditer(paragraph))
    if not matches:
        return [paragraph]
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        if match.start() > cursor:
            pieces.append(paragraph[cursor : match.start()])
        cursor = match.start()
    pieces.append(paragraph[cursor:])
    return pieces


def _short(span: str, *, limit: int = 120) -> str:
    """Truncate ``span`` for inclusion in a rejection report."""
    flat = " ".join(span.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


__all__ = [
    "ConcernExtractor",
    "ExtractionResult",
    "Rejection",
]
