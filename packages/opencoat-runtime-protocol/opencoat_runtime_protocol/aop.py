"""AOP (AspectJ) executable view of a :class:`~envelopes.Concern`.

OpenCOAT keeps **Concern** as the only runtime unit. This module normalizes
legacy single ``pointcut`` / ``advice`` / ``weaving_policy`` fields and the
AOP lists (``pointcuts`` / ``advices`` / ``declarations``) into one
executable shape the matcher and weaver consume.

Surface syntax (optional ``PointcutDef.expression``) uses a small subset of
AOP pointcut designators (AspectJ), e.g.::

    user_message() && args("rm -rf")
    before_tool_call()
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .envelopes import (
    Advice,
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    ConcernDeclaration,
    ConcernRelationType,
    DeclarePrecedence,
    Pointcut,
    PointcutDef,
    PointcutMatch,
    WeavingPolicy,
)

if TYPE_CHECKING:
    from .envelopes import JoinpointSelector

_JOINPOINT_CALL = re.compile(r"([a-z][a-z0-9_]*)\s*\(\s*\)")
_ARGS_KEYWORDS = re.compile(
    r"""args\s*\(\s*(?:"([^"]+)"|'([^']+)'|([^)]+))\s*\)""",
    re.IGNORECASE,
)


def parse_pointcut_expression(expression: str) -> tuple[list[str], PointcutMatch | None]:
    """Parse a minimal AOP (AspectJ) pointcut expression into joinpoints + match."""
    expr = expression.strip()
    if not expr:
        return [], None

    joinpoints: list[str] = []
    keywords: list[str] = []

    for part in re.split(r"\s*&&\s*", expr):
        part = part.strip()
        if not part:
            continue
        for m in _JOINPOINT_CALL.finditer(part):
            name = m.group(1)
            if name not in ("args", "execution", "call", "within", "adviceexecution"):
                joinpoints.append(name)
        for m in _ARGS_KEYWORDS.finditer(part):
            kw = m.group(1) or m.group(2) or m.group(3)
            if kw:
                keywords.extend(k.strip() for k in kw.split(",") if k.strip())

    match = PointcutMatch(any_keywords=keywords) if keywords else None
    return joinpoints, match


def pointcut_def_to_pointcut(defn: PointcutDef) -> Pointcut:
    """Materialize a :class:`Pointcut` for the matcher."""
    joinpoints: list[str] | list[JoinpointSelector] = list(defn.joinpoints)
    match = defn.match
    if defn.expression:
        parsed_jps, parsed_match = parse_pointcut_expression(defn.expression)
        if not joinpoints and parsed_jps:
            joinpoints = parsed_jps
        if match is None and parsed_match is not None:
            match = parsed_match
    return Pointcut(
        joinpoints=joinpoints,
        match=match,
        context_predicates=list(defn.context_predicates),
    )


def _default_advice_kind(template: AdviceType | str | None) -> AdviceKind:
    if template is None:
        return AdviceKind.BEFORE
    t = AdviceType(template) if not isinstance(template, AdviceType) else template
    if t in (AdviceType.VERIFICATION_RULE, AdviceType.REFLECTION_PROMPT, AdviceType.ESCALATION_NOTICE):
        return AdviceKind.AFTER
    if t in (AdviceType.SUPPRESS_INSTRUCTION, AdviceType.REWRITE_GUIDANCE):
        return AdviceKind.AROUND
    return AdviceKind.BEFORE


def legacy_to_aop_lists(
    concern: Concern,
) -> tuple[list[PointcutDef], list[AopAdvice], list[ConcernDeclaration]]:
    """Build AOP lists from legacy single fields."""
    pointcuts: list[PointcutDef] = []
    advices: list[AopAdvice] = []
    declarations: list[ConcernDeclaration] = list(concern.declarations)

    if concern.pointcut is not None:
        pc = concern.pointcut
        pointcuts.append(
            PointcutDef(
                id="pc-default",
                joinpoints=list(pc.joinpoints) if pc.joinpoints else [],
                match=pc.match,
                context_predicates=list(pc.context_predicates),
            )
        )

    if concern.advice is not None:
        adv = concern.advice
        effect = concern.weaving_policy
        advices.append(
            AopAdvice(
                id="adv-default",
                kind=_default_advice_kind(adv.type),
                pointcut_ref="pc-default",
                content=adv.content,
                template=AdviceType(adv.type) if adv.type else None,
                rationale=adv.rationale,
                max_tokens=adv.max_tokens,
                params=adv.params,
                effect=effect,
            )
        )

    for rel in concern.relations:
        if rel.relation_type == ConcernRelationType.DECLARES_PRECEDENCE_OVER:
            declarations.append(
                DeclarePrecedence(order=[concern.id, rel.target_concern_id])
            )

    return pointcuts, advices, declarations


def legacy_from_primary(
    pointcuts: list[PointcutDef],
    advices: list[AopAdvice],
) -> tuple[Pointcut | None, Advice | None, WeavingPolicy | None]:
    """Derive legacy fields from the primary AOP entries."""
    pointcut: Pointcut | None = None
    if pointcuts:
        pointcut = pointcut_def_to_pointcut(pointcuts[0])

    advice: Advice | None = None
    weaving: WeavingPolicy | None = None
    if advices:
        primary = advices[0]
        template = primary.template or AdviceType.RESPONSE_REQUIREMENT
        advice = Advice(
            type=template,
            content=primary.content,
            rationale=primary.rationale,
            max_tokens=primary.max_tokens,
            params=primary.params,
        )
        weaving = primary.effect

    return pointcut, advice, weaving


def sync_concern_aop(concern: Concern) -> Concern:
    """Return a concern with legacy and AOP shapes mutually populated."""
    has_lists = bool(concern.pointcuts or concern.advices)
    has_legacy = concern.pointcut is not None or concern.advice is not None
    if has_lists and has_legacy:
        return concern

    updates: dict[str, object] = {}
    if not has_lists and has_legacy:
        lp, la, ld = legacy_to_aop_lists(concern)
        if lp:
            updates["pointcuts"] = lp
        if la:
            updates["advices"] = la
        if ld and not concern.declarations:
            updates["declarations"] = ld
        return concern.model_copy(update=updates)

    if has_lists and not has_legacy:
        lp, la, lw = legacy_from_primary(list(concern.pointcuts), list(concern.advices))
        if lp is not None:
            updates["pointcut"] = lp
        if la is not None:
            updates["advice"] = la
        if lw is not None:
            updates["weaving_policy"] = lw
        return concern.model_copy(update=updates)

    return concern


def primary_pointcut(concern: Concern) -> Pointcut | None:
    """Pointcut used by the matcher (legacy field or first ``pointcuts[]`` entry)."""
    if concern.pointcut is not None:
        return concern.pointcut
    if concern.pointcuts:
        return pointcut_def_to_pointcut(concern.pointcuts[0])
    return None


def primary_advice(concern: Concern) -> Advice | None:
    """Legacy-shaped advice for generators and verifier."""
    if concern.advice is not None:
        return concern.advice
    if not concern.advices:
        return None
    aj = concern.advices[0]
    template = aj.template or AdviceType.RESPONSE_REQUIREMENT
    return Advice(
        type=template,
        content=aj.content,
        rationale=aj.rationale,
        max_tokens=aj.max_tokens,
        params=aj.params,
    )


def primary_weaving(concern: Concern) -> WeavingPolicy | None:
    if concern.weaving_policy is not None:
        return concern.weaving_policy
    if concern.advices and concern.advices[0].effect is not None:
        return concern.advices[0].effect
    return None


def has_executable_pointcut(concern: Concern) -> bool:
    return primary_pointcut(concern) is not None
