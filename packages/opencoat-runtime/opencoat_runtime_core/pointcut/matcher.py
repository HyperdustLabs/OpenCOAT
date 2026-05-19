"""Pointcut matcher — default :class:`MatcherPlugin` implementation.

Pipeline (per joinpoint):

1. **Joinpoint filter**  — if the pointcut declares ``joinpoints``, the
   incoming :class:`JoinpointEvent` must match either by exact name (string
   list) or by every non-``None`` field of a :class:`JoinpointSelector`.
2. **Match block**       — every non-``None`` field in
   ``pointcut.match`` runs through the corresponding strategy under
   :mod:`.strategies`. Strategies are AND-combined; reasons are
   concatenated; the final score is the *minimum* strategy score so a
   single weak hit can't drag a strong block over the threshold.
3. **Context predicates** — top-level ``context_predicates`` are
   evaluated against the runtime context map. Same AND semantics.

The matcher is stateless. It compiles incoming :class:`Pointcut` objects
on the fly via :class:`PointcutCompiler`; callers that match the same
pointcut repeatedly should compile once and reuse :meth:`match_compiled`.
"""

from __future__ import annotations

from opencoat_runtime_protocol import JoinpointEvent, JoinpointSelector, Pointcut

from ..joinpoint.aliases import joinpoint_names_match
from ..ports.matcher import MatcherPlugin, MatchResult
from ..types import JSON
from ._context import (
    CONTEXT_OPERATORS,
    MISSING_VALUE,
    apply_operator,
    context_lookup,
    resolve_value,
)
from .compiler import CompiledPointcut, PointcutCompiler, match_block_is_executable
from .strategies import (
    claim,
    confidence,
    history,
    keyword,
    regex,
    risk,
    semantic,
    structure,
)


class PointcutMatcher(MatcherPlugin):
    """Default matcher composing the per-strategy modules under :mod:`.strategies`."""

    def __init__(self, compiler: PointcutCompiler | None = None) -> None:
        self._compiler = compiler or PointcutCompiler()

    # ------------------------------------------------------------------
    # MatcherPlugin protocol
    # ------------------------------------------------------------------

    def match(
        self,
        pointcut: Pointcut,
        joinpoint: JoinpointEvent,
        context: JSON | None = None,
    ) -> MatchResult:
        compiled = self._compiler.compile(pointcut)
        return self.match_compiled(compiled, joinpoint, context)

    def match_compiled(
        self,
        compiled: CompiledPointcut,
        joinpoint: JoinpointEvent,
        context: JSON | None = None,
    ) -> MatchResult:
        if not _joinpoint_passes(compiled, joinpoint):
            return MatchResult(matched=False, score=0.0, reasons=())

        raw_match = compiled.source.match
        if (
            raw_match is not None
            and not match_block_is_executable(raw_match)
            and not compiled.has_context_predicates
        ):
            return MatchResult(
                matched=False,
                score=0.0,
                reasons=("miss:inert_match_block",),
            )

        scores: list[float] = []
        reasons: list[str] = []

        if compiled.has_match_block:
            block_scores, block_reasons = _evaluate_match_block(compiled, joinpoint, context)
            if block_scores is None:
                return MatchResult(matched=False, score=0.0, reasons=tuple(block_reasons))
            scores.extend(block_scores)
            reasons.extend(block_reasons)

        if compiled.has_context_predicates:
            ok, ctx_reasons = _evaluate_context_predicates(compiled.source, context)
            if not ok:
                return MatchResult(matched=False, score=0.0, reasons=tuple(ctx_reasons))
            scores.append(1.0)
            reasons.extend(ctx_reasons)

        if not compiled.has_match_block and not compiled.has_context_predicates:
            scores.append(1.0)
            reasons.append("joinpoint_filter")

        return MatchResult(
            matched=True,
            score=min(scores) if scores else 1.0,
            reasons=tuple(reasons),
        )


# ---------------------------------------------------------------------------
# Joinpoint filter
# ---------------------------------------------------------------------------


def _joinpoint_passes(compiled: CompiledPointcut, jp: JoinpointEvent) -> bool:
    if not compiled.joinpoint_names and not compiled.joinpoint_selectors:
        return True
    if any(joinpoint_names_match(name, jp.name) for name in compiled.joinpoint_names):
        return True
    return any(_selector_matches(sel, jp) for sel in compiled.joinpoint_selectors)


def _selector_matches(sel: JoinpointSelector, jp: JoinpointEvent) -> bool:
    payload = jp.payload or {}
    if sel.level is not None:
        wanted = _level_to_int(sel.level)
        if wanted is not None and jp.level != wanted:
            return False
    if sel.name is not None and sel.name != jp.name:
        return False
    if sel.path is not None:
        path = payload.get("path") if isinstance(payload.get("path"), str) else jp.name
        if path != sel.path:
            return False
    if sel.semantic_type is not None and payload.get("semantic_type") != sel.semantic_type:
        return False
    if sel.field is not None and payload.get("field") != sel.field:
        return False
    if sel.match:
        text = " ".join(
            str(v)
            for v in (
                payload.get("raw_text"),
                payload.get("text"),
                payload.get("token"),
            )
            if isinstance(v, str)
        )
        if not any(needle in text for needle in sel.match):
            return False
    return True


_LEVEL_MAP = {
    "runtime": 0,
    "lifecycle": 1,
    "message": 2,
    "prompt_section": 3,
    "span": 4,
    "token": 5,
    "structure_field": 6,
    "thought_unit": 7,
}


def _level_to_int(level_value: object) -> int | None:
    if isinstance(level_value, int):
        return level_value
    if isinstance(level_value, str):
        return _LEVEL_MAP.get(level_value)
    return None


# ---------------------------------------------------------------------------
# Match block dispatch
# ---------------------------------------------------------------------------


def _evaluate_match_block(
    compiled: CompiledPointcut,
    jp: JoinpointEvent,
    context: JSON | None,
) -> tuple[list[float] | None, list[str]]:
    """Run every active strategy in the match block.

    Returns ``(scores, reasons)`` on success and ``(None, [<miss-reason>])``
    on the first failed sub-strategy so the matcher short-circuits.
    """
    block = compiled.source.match
    assert block is not None
    scores: list[float] = []
    reasons: list[str] = []

    if compiled.any_keywords_lower or compiled.all_keywords_lower:
        result = keyword.apply(
            jp,
            any_keywords=list(compiled.any_keywords_lower or ()) or None,
            all_keywords=list(compiled.all_keywords_lower or ()) or None,
            case_sensitive=False,
            context=context,
        )
        if not result.matched:
            return None, ["miss:keyword"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if compiled.regex is not None:
        result = regex.apply(jp, compiled.regex, context)
        if not result.matched:
            return None, ["miss:regex"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if block.semantic_intent is not None:
        result = semantic.apply(jp, block.semantic_intent, context=context)
        if not result.matched:
            return None, ["miss:semantic"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if block.structure is not None:
        result = structure.apply(
            jp,
            field=block.structure.field,
            operator=block.structure.operator,
            value=block.structure.value,
            value_ref=block.structure.value_ref,
            context=context,
        )
        if not result.matched:
            return None, ["miss:structure"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if block.confidence is not None:
        result = confidence.apply(
            jp,
            op=block.confidence.op,
            threshold=block.confidence.threshold,
            context=context,
        )
        if not result.matched:
            return None, ["miss:confidence"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if block.risk is not None:
        result = risk.apply(jp, op=block.risk.op, level=block.risk.level, context=context)
        if not result.matched:
            return None, ["miss:risk"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if block.claim is not None:
        result = claim.apply(
            jp,
            claim_type=block.claim.claim_type,
            evidence_required=block.claim.evidence_required,
            context=context,
        )
        if not result.matched:
            return None, ["miss:claim"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    if block.history is not None:
        result = history.apply(jp, block.history, context)
        if not result.matched:
            return None, ["miss:history"]
        scores.append(result.score)
        reasons.extend(result.reasons)

    return scores, reasons


# ---------------------------------------------------------------------------
# Context predicates
# ---------------------------------------------------------------------------


def _evaluate_context_predicates(source: Pointcut, context: JSON | None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for predicate in source.context_predicates:
        if predicate.op not in CONTEXT_OPERATORS:
            return False, [f"miss:context_op:{predicate.op}"]
        target = context_lookup(context, predicate.key)
        if target is MISSING_VALUE:
            return False, [f"miss:context_key:{predicate.key}"]
        compare = resolve_value(
            value=predicate.value, value_ref=predicate.value_ref, context=context
        )
        if compare is MISSING_VALUE:
            return False, [f"miss:context_value_ref:{predicate.value_ref}"]
        if not apply_operator(predicate.op, target, compare):
            return False, [f"miss:context:{predicate.key} {predicate.op}"]
        reasons.append(f"context:{predicate.key} {predicate.op} {compare!r}")
    return True, reasons


__all__ = ["PointcutMatcher"]
