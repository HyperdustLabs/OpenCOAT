"""Stochastic rewrite gate for MAN slow dynamics."""

from __future__ import annotations

import random

from opencoat_runtime_core.credit.rewrite_gate import RewriteGate


def test_rewrite_gate_accepts_by_exp_delta_f_over_temperature() -> None:
    gate = RewriteGate(temperature=1.0, rng=random.Random(15))
    rejected = gate.evaluate("connect", delta_f=0.1)
    assert not rejected.accepted
    assert 0.0 < rejected.acceptance_rate < 1.0

    accepted = gate.evaluate("connect", delta_f=0.1)
    assert accepted.accepted
    assert accepted.acceptance_rate == rejected.acceptance_rate


def test_rewrite_gate_always_accepts_downhill_rewrite_except_zero_probability_edge() -> None:
    gate = RewriteGate(temperature=1.0, rng=random.Random(999))
    out = gate.evaluate("prune", delta_f=-0.2)
    assert out.accepted
    assert out.acceptance_rate == 1.0
