"""Tier-1 responsibility weights ``ρ`` (morphogenetic §3)."""

from __future__ import annotations

from dataclasses import dataclass

HARD_CONTRIB = 1.0
SOFT_CONTRIB = 0.35


@dataclass(frozen=True)
class ActiveAspect:
    """One activated aspect at weave time with routing score ``a_i``."""

    concern_id: str
    activation_score: float
    hard: bool = False

    @property
    def contrib(self) -> float:
        return HARD_CONTRIB if self.hard else SOFT_CONTRIB


def tier1_responsibility(active: list[ActiveAspect]) -> dict[str, float]:
    """``ρ_i = a_i·contrib_i / Σ_j a_j·contrib_j``."""
    if not active:
        return {}
    weights = {a.concern_id: max(0.0, a.activation_score) * a.contrib for a in active}
    total = sum(weights.values())
    if total <= 0.0:
        n = len(active)
        return {a.concern_id: 1.0 / n for a in active}
    return {cid: w / total for cid, w in weights.items()}


def uniform_responsibility(active: list[ActiveAspect]) -> dict[str, float]:
    """Ablation: equal ρ (paper §8 — raises false split rate)."""
    if not active:
        return {}
    share = 1.0 / len(active)
    return {a.concern_id: share for a in active}


__all__ = [
    "HARD_CONTRIB",
    "SOFT_CONTRIB",
    "ActiveAspect",
    "tier1_responsibility",
    "uniform_responsibility",
]
