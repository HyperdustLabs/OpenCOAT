"""Connectome split primitive (v0.3 morphogenetic §5 — cold-path prototype)."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from opencoat_runtime_protocol import (
    AopAdvice,
    Concern,
    PointcutDef,
    PointcutMatch,
)


@dataclass(frozen=True)
class SplitProposal:
    parent_id: str
    child_a_id: str
    child_b_id: str
    keywords_a: tuple[str, ...]
    keywords_b: tuple[str, ...]


def collect_pointcut_keywords(concern: Concern) -> list[str]:
    """Union of ``any_keywords`` across executable pointcuts (deterministic order)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for pc in concern.pointcuts:
        if pc.match and pc.match.any_keywords:
            for kw in pc.match.any_keywords:
                if kw not in seen:
                    seen.add(kw)
                    ordered.append(kw)
    if concern.pointcut and concern.pointcut.match and concern.pointcut.match.any_keywords:
        for kw in concern.pointcut.match.any_keywords:
            if kw not in seen:
                seen.add(kw)
                ordered.append(kw)
    return ordered


def propose_keyword_split(concern: Concern) -> SplitProposal | None:
    """Deterministic binary split when ≥2 keywords (domain conservation)."""
    if concern.reflex:
        return None
    if "--" in concern.id:
        return None
    keywords = collect_pointcut_keywords(concern)
    if len(keywords) < 2:
        return None
    sorted_keys = sorted(set(keywords))
    mid = len(sorted_keys) // 2
    if mid <= 0 or mid >= len(sorted_keys):
        return None
    keys_a = tuple(sorted_keys[:mid])
    keys_b = tuple(sorted_keys[mid:])
    return SplitProposal(
        parent_id=concern.id,
        child_a_id=f"{concern.id}--a",
        child_b_id=f"{concern.id}--b",
        keywords_a=keys_a,
        keywords_b=keys_b,
    )


def _child_from_parent(
    parent: Concern,
    *,
    child_id: str,
    keywords: tuple[str, ...],
    suffix: str,
) -> Concern:
    pointcuts = copy.deepcopy(parent.pointcuts)
    if not pointcuts and parent.pointcut:
        joinpoints = list(parent.pointcut.joinpoints or ["before_response"])
        expr = parent.pointcut.expression if hasattr(parent.pointcut, "expression") else None
        if not expr and joinpoints:
            expr = f"{joinpoints[0]}()"
        pointcuts = [
            PointcutDef(
                id=f"pc-{suffix}",
                expression=expr or "before_response()",
                joinpoints=joinpoints,
                match=PointcutMatch(any_keywords=list(keywords)),
            )
        ]
    else:
        for pc in pointcuts:
            pc.match = PointcutMatch(any_keywords=list(keywords))

    advices: list[AopAdvice] = []
    for adv in parent.advices:
        cloned = adv.model_copy(deep=True)
        cloned.id = f"{adv.id}-{suffix}"
        advices.append(cloned)

    return parent.model_copy(
        update={
            "id": child_id,
            "name": f"{parent.name} ({suffix})",
            "description": (f"Split child {suffix} of {parent.id}; keywords={list(keywords)}"),
            "pointcuts": pointcuts,
            "advices": advices,
            "pointcut": None,
            "advice": None,
            "lifecycle_state": "created",
            "reflex": False,
        }
    )


def materialize_split(proposal: SplitProposal, parent: Concern) -> tuple[Concern, Concern]:
    """Build two specialized children covering ``dom(a₁) ⊎ dom(a₂) = dom(a)``."""
    child_a = _child_from_parent(
        parent,
        child_id=proposal.child_a_id,
        keywords=proposal.keywords_a,
        suffix="a",
    )
    child_b = _child_from_parent(
        parent,
        child_id=proposal.child_b_id,
        keywords=proposal.keywords_b,
        suffix="b",
    )
    return child_a, child_b


__all__ = [
    "SplitProposal",
    "collect_pointcut_keywords",
    "materialize_split",
    "propose_keyword_split",
]
