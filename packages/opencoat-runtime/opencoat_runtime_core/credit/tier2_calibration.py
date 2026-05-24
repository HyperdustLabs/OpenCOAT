"""Tier-2 counterfactual calibration scaffold (morphogenetic §8)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from opencoat_runtime_core.ports import LLMClient


@dataclass(frozen=True)
class Tier2CalibrationResult:
    concern_id: str
    tier1_gain: float
    tier2_correction: float
    samples: int
    seed: int


@dataclass
class Tier2Calibrator:
    """Optional LLM counterfactual replay with fixed seed (statistical tier-2)."""

    llm: LLMClient | None = None
    samples: int = 3
    seed: int = 42
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def calibrate_split(
        self,
        concern_id: str,
        *,
        tier1_gain: float,
        context: str,
    ) -> Tier2CalibrationResult:
        """Estimate correction to tier-1 separability gain (stub without LLM)."""
        correction = 0.0
        if self.llm is not None:
            # Prototype: jitter around tier-1; real impl would replay turn with LLM.
            draws = [self._rng.uniform(-0.05, 0.05) for _ in range(self.samples)]
            correction = sum(draws) / len(draws)
        return Tier2CalibrationResult(
            concern_id=concern_id,
            tier1_gain=tier1_gain,
            tier2_correction=correction,
            samples=self.samples,
            seed=self.seed,
        )


__all__ = ["Tier2CalibrationResult", "Tier2Calibrator"]
