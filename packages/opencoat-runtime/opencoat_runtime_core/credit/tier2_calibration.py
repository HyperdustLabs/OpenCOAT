"""Tier-2 leave-one-out calibration on replay buffer (morphogenetic §3, §8)."""

from __future__ import annotations

from dataclasses import dataclass

from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.credit.split_spec import SplitPartition, separability_gain
from opencoat_runtime_core.ports import LLMClient


@dataclass(frozen=True)
class Tier2CalibrationResult:
    concern_id: str
    tier1_gain: float
    tier2_correction: float
    calibrated_gain: float
    samples: int
    seed: int


@dataclass
class Tier2Calibrator:
    """Deterministic LOO: drop each feature value, measure ΔG (no LLM required)."""

    llm: LLMClient | None = None
    samples: int = 3
    seed: int = 42
    min_samples: int = 8

    def calibrate_split(
        self,
        concern_id: str,
        *,
        tier1_gain: float,
        buffer: ConcernRtBuffer,
        partition: SplitPartition | None = None,
        context: str = "",
    ) -> Tier2CalibrationResult:
        rows = buffer.samples(concern_id)
        if len(rows) < self.min_samples or partition is None:
            return Tier2CalibrationResult(
                concern_id=concern_id,
                tier1_gain=tier1_gain,
                tier2_correction=0.0,
                calibrated_gain=tier1_gain,
                samples=len(rows),
                seed=self.seed,
            )

        corrections: list[float] = []
        features = sorted({s.feature for s in rows if s.feature})
        for feat in features[: max(1, self.samples)]:
            left = [i for i, s in enumerate(rows) if s.feature != feat]
            right = [i for i, s in enumerate(rows) if s.feature == feat]
            if not left or not right:
                continue
            part = SplitPartition(
                axis="loo_feature",
                threshold=feat,
                left_indices=tuple(left),
                right_indices=tuple(right),
                separability_gain=0.0,
                reward_variance=0.0,
                mean_left=0.0,
                mean_right=0.0,
            )
            g_loo = separability_gain(rows, part)
            corrections.append(g_loo - tier1_gain)

        correction = sum(corrections) / len(corrections) if corrections else 0.0
        if self.llm is not None:
            # Optional future: LLM counterfactual replay; keep deterministic default.
            correction *= 0.5

        return Tier2CalibrationResult(
            concern_id=concern_id,
            tier1_gain=tier1_gain,
            tier2_correction=correction,
            calibrated_gain=tier1_gain + correction,
            samples=len(rows),
            seed=self.seed,
        )


__all__ = ["Tier2CalibrationResult", "Tier2Calibrator"]
