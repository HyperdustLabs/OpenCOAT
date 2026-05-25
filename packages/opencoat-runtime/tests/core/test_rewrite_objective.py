"""Variational objective proxies for structural rewrites."""

from __future__ import annotations

from opencoat_runtime_core.credit.rewrite_objective import (
    score_connect,
    score_lift,
    score_merge,
    score_prune,
)


def test_connect_objective_balances_surprise_against_edge_complexity() -> None:
    out = score_connect(coactivation=0.2, beta=0.01)
    assert out.primitive == "connect"
    assert out.delta_surprise == -0.2
    assert out.delta_complexity == 1.0
    assert out.delta_f < 0


def test_connect_objective_uses_empirical_reward_signal() -> None:
    out = score_connect(coactivation=0.2, reward_mean=0.5, beta=0.01)
    assert out.reason == "coactivation_reward"
    assert out.delta_surprise == -0.1


def test_prune_objective_reduces_complexity_for_cold_edge() -> None:
    out = score_prune(weight=0.05, threshold=0.15, beta=0.01)
    assert out.primitive == "prune"
    assert out.delta_surprise == 0.05
    assert out.delta_complexity < 0
    assert out.delta_f < out.delta_surprise


def test_lift_objective_charges_node_and_edge_complexity() -> None:
    out = score_lift(coalition_size=2, beta=0.01)
    assert out.primitive == "lift"
    assert out.delta_surprise == -2.0
    assert out.delta_complexity == 6.0
    assert out.delta_f < 0


def test_lift_objective_uses_empirical_reward_signal() -> None:
    out = score_lift(coalition_size=2, reward_mean=0.25, beta=0.01)
    assert out.reason == "cofire_reward_coalition"
    assert out.delta_surprise == -0.5


def test_merge_objective_rewards_redundancy_and_complexity_reduction() -> None:
    out = score_merge(keyword_overlap=3, beta=0.01)
    assert out.primitive == "merge"
    assert out.delta_surprise == -0.75
    assert out.delta_complexity == -4.0
    assert out.delta_f < 0


def test_merge_objective_penalizes_reward_gap() -> None:
    out = score_merge(keyword_overlap=3, reward_gap=0.5, beta=0.01)
    assert out.reason == "redundancy_reward_gap"
    assert out.delta_surprise == -0.25
