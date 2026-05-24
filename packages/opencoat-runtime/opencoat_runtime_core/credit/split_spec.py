"""Split guards H(a), G(a) and axis-aligned partition (morphogenetic §5)."""

from __future__ import annotations

from dataclasses import dataclass

from opencoat_runtime_core.credit.delta_f import DeltaFResult, evaluate_delta_f
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer, RtSample


@dataclass(frozen=True)
class SplitPartition:
    axis: str
    threshold: str
    left_indices: tuple[int, ...]
    right_indices: tuple[int, ...]
    separability_gain: float
    reward_variance: float
    mean_left: float
    mean_right: float


@dataclass(frozen=True)
class SplitGuardResult:
    eligible: bool
    partition: SplitPartition | None
    delta_f: DeltaFResult | None
    reason: str = ""


def reward_variance(samples: list[RtSample]) -> float:
    if len(samples) < 2:
        return 0.0
    mean = sum(s.r for s in samples) / len(samples)
    return sum((s.r - mean) ** 2 for s in samples) / len(samples)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def separability_gain(samples: list[RtSample], partition: SplitPartition) -> float:
    """``G(a) = Var[r] − (p₁·Var[r|C₁] + p₂·Var[r|C₂])``."""
    all_r = [s.r for s in samples]
    left_r = [samples[i].r for i in partition.left_indices]
    right_r = [samples[i].r for i in partition.right_indices]
    n = len(all_r)
    if n == 0:
        return 0.0
    p1 = len(left_r) / n
    p2 = len(right_r) / n
    return _variance(all_r) - (p1 * _variance(left_r) + p2 * _variance(right_r))


def find_best_axis_partition(samples: list[RtSample]) -> SplitPartition | None:
    """Deterministic axis-aligned split over feature tokens (O(d·W))."""
    if len(samples) < 4:
        return None
    features = sorted({s.feature for s in samples if s.feature})
    if not features:
        features = ["_"]

    best: SplitPartition | None = None
    for axis in features:
        if axis == "_":
            left_idx = tuple(range(len(samples) // 2))
            right_idx = tuple(range(len(samples) // 2, len(samples)))
            left_r = [samples[i].r for i in left_idx]
            right_r = [samples[i].r for i in right_idx]
            part = SplitPartition(
                axis="_index",
                threshold=str(len(samples) // 2),
                left_indices=left_idx,
                right_indices=right_idx,
                separability_gain=0.0,
                reward_variance=reward_variance(samples),
                mean_left=sum(left_r) / max(len(left_r), 1),
                mean_right=sum(right_r) / max(len(right_r), 1),
            )
            part = part.__class__(
                **{
                    **part.__dict__,
                    "separability_gain": separability_gain(samples, part),
                }
            )
            if best is None or part.separability_gain > best.separability_gain:
                best = part
            continue

        for feat in features:
            left_idx = tuple(i for i, s in enumerate(samples) if feat in s.feature)
            right_idx = tuple(i for i, s in enumerate(samples) if feat not in s.feature)
            if not left_idx or not right_idx:
                continue
            left_r = [samples[i].r for i in left_idx]
            right_r = [samples[i].r for i in right_idx]
            part = SplitPartition(
                axis=feat,
                threshold=feat,
                left_indices=left_idx,
                right_indices=right_idx,
                separability_gain=0.0,
                reward_variance=reward_variance(samples),
                mean_left=sum(left_r) / len(left_r),
                mean_right=sum(right_r) / len(right_r),
            )
            part = part.__class__(
                **{**part.__dict__, "separability_gain": separability_gain(samples, part)}
            )
            if best is None or part.separability_gain > best.separability_gain:
                best = part
    return best


def evaluate_split_guards(
    buffer: ConcernRtBuffer,
    concern_id: str,
    *,
    theta_h: float = 0.02,
    theta_sep: float = 0.15,
    n_min: int = 8,
    delta_min: float = 0.05,
    temperature: float = 1.0,
) -> SplitGuardResult:
    samples = buffer.samples(concern_id)
    n = len(samples)
    if n < n_min:
        return SplitGuardResult(False, None, None, reason=f"n({concern_id})={n} < n_min")

    h_a = reward_variance(samples)
    if h_a < theta_h:
        return SplitGuardResult(False, None, None, reason=f"H(a)={h_a:.4f} < θ_H")

    partition = find_best_axis_partition(samples)
    if partition is None:
        return SplitGuardResult(False, None, None, reason="no separable partition")

    if h_a <= 0 or partition.separability_gain / h_a < theta_sep:
        return SplitGuardResult(
            False,
            partition,
            None,
            reason=f"G/H={partition.separability_gain / max(h_a, 1e-9):.4f} < θ_sep",
        )

    if abs(partition.mean_left - partition.mean_right) < delta_min:
        return SplitGuardResult(
            False,
            partition,
            None,
            reason=f"|r̄₁−r̄₂|={abs(partition.mean_left - partition.mean_right):.4f} < δ",
        )

    delta = evaluate_delta_f(
        separability_gain=partition.separability_gain,
        temperature=temperature,
    )
    if not delta.accept:
        return SplitGuardResult(False, partition, delta, reason="ΔF ≥ 0")

    return SplitGuardResult(True, partition, delta, reason="accepted")


__all__ = [
    "SplitGuardResult",
    "SplitPartition",
    "evaluate_split_guards",
    "find_best_axis_partition",
    "reward_variance",
    "separability_gain",
]
