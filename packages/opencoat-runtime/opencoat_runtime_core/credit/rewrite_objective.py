"""Variational objective proxies for MAN structural rewrites.

The paper objective is ``F = Surprise + β·Complexity``. Runtime rewrites do
not yet have full counterfactual surprise estimates for every primitive, so
this module centralizes the deterministic tier-1 proxies used by ``⇩_slow``.
Keeping them here makes each approximation auditable and replaceable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RewriteObjectiveResult:
    primitive: str
    delta_surprise: float
    delta_complexity: float
    beta: float
    delta_f: float
    reason: str


def score_connect(
    *,
    coactivation: float,
    reward_mean: float | None = None,
    edge_cost: float = 1.0,
    beta: float = 0.01,
) -> RewriteObjectiveResult:
    """Connect if co-activation surprise reduction pays for one edge."""
    reward_signal = 1.0 if reward_mean is None else max(0.0, reward_mean)
    delta_surprise = -max(0.0, coactivation) * reward_signal
    delta_complexity = max(0.0, edge_cost)
    reason = "coactivation" if reward_mean is None else "coactivation_reward"
    return _result("connect", delta_surprise, delta_complexity, beta, reason)


def score_prune(
    *,
    weight: float,
    threshold: float,
    edge_cost: float = 1.0,
    beta: float = 0.01,
) -> RewriteObjectiveResult:
    """Prune low-weight edges: little surprise cost, lower complexity."""
    coldness = max(0.0, threshold - weight)
    delta_surprise = max(0.0, weight)
    delta_complexity = -max(0.0, edge_cost + coldness)
    return _result("prune", delta_surprise, delta_complexity, beta, "low_weight")


def score_lift(
    *,
    coalition_size: int,
    cofire_strength: float = 1.0,
    reward_mean: float | None = None,
    node_cost: float = 4.0,
    edge_cost: float = 1.0,
    beta: float = 0.01,
) -> RewriteObjectiveResult:
    """Lift co-firing coalitions into one higher-order aspect."""
    size = max(0, coalition_size)
    reward_signal = 1.0 if reward_mean is None else max(0.0, reward_mean)
    delta_surprise = -max(0.0, cofire_strength) * reward_signal * size
    delta_complexity = max(0.0, node_cost + edge_cost * size)
    reason = "cofire_coalition" if reward_mean is None else "cofire_reward_coalition"
    return _result("lift", delta_surprise, delta_complexity, beta, reason)


def score_merge(
    *,
    keyword_overlap: int,
    reward_gap: float = 0.0,
    node_savings: float = 4.0,
    beta: float = 0.01,
) -> RewriteObjectiveResult:
    """Merge near duplicates: small abstraction risk, lower complexity."""
    overlap = max(0, keyword_overlap)
    delta_surprise = abs(reward_gap) - 0.25 * overlap
    delta_complexity = -max(0.0, node_savings)
    reason = "redundancy" if reward_gap == 0.0 else "redundancy_reward_gap"
    return _result("merge", delta_surprise, delta_complexity, beta, reason)


def _result(
    primitive: str,
    delta_surprise: float,
    delta_complexity: float,
    beta: float,
    reason: str,
) -> RewriteObjectiveResult:
    delta_f = delta_surprise + beta * delta_complexity
    return RewriteObjectiveResult(
        primitive=primitive,
        delta_surprise=delta_surprise,
        delta_complexity=delta_complexity,
        beta=beta,
        delta_f=delta_f,
        reason=reason,
    )


__all__ = [
    "RewriteObjectiveResult",
    "score_connect",
    "score_lift",
    "score_merge",
    "score_prune",
]
