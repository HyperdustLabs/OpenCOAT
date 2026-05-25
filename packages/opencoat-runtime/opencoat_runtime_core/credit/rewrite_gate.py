"""Stochastic rewrite acceptance for MAN ``⇩_slow`` primitives."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RewriteGateResult:
    primitive: str
    delta_f: float
    temperature: float
    acceptance_rate: float
    sample: float
    accepted: bool
    reason: str


class RewriteGate:
    """Metropolis-style gate: accept with ``min(1, exp(-ΔF/T))``."""

    def __init__(self, *, temperature: float = 1.0, rng: random.Random | None = None) -> None:
        self.temperature = temperature
        self._rng = rng or random.Random(0)

    def evaluate(self, primitive: str, *, delta_f: float) -> RewriteGateResult:
        rate = min(1.0, math.exp(-delta_f / max(self.temperature, 1e-6)))
        sample = self._rng.random()
        accepted = sample < rate
        op = "<" if accepted else ">="
        return RewriteGateResult(
            primitive=primitive,
            delta_f=delta_f,
            temperature=self.temperature,
            acceptance_rate=rate,
            sample=sample,
            accepted=accepted,
            reason=f"{primitive} {'accepted' if accepted else 'rejected'} u={sample:.4f} {op} p={rate:.4f}",
        )


__all__ = ["RewriteGate", "RewriteGateResult"]
