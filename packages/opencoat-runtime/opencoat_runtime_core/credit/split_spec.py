"""Split guards H(a), G(a) and axis-aligned partition (morphogenetic §5)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from opencoat_runtime_core.credit.delta_f import DeltaFResult, evaluate_delta_f
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer, RtSample

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{1,31}")


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
    acceptance_sample: float | None = None


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


def _feature_tokens(feature: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(feature.lower()))


def is_categorical_feature_axis(samples: list[RtSample]) -> bool:
    """Low-cardinality stimulus labels (scenario id, tool class), not free text."""
    feats = [s.feature for s in samples if s.feature]
    if not feats:
        return False
    n = len(feats)
    n_unique = len(set(feats))
    max_len = max(len(f) for f in feats)
    if max_len > 64:
        return False
    if n_unique <= max(4, n // 2):
        return True
    return n_unique / n <= 0.35


def _partition_from_indices(
    samples: list[RtSample],
    *,
    axis: str,
    threshold: str,
    left_idx: tuple[int, ...],
    right_idx: tuple[int, ...],
) -> SplitPartition | None:
    if not left_idx or not right_idx:
        return None
    left_r = [samples[i].r for i in left_idx]
    right_r = [samples[i].r for i in right_idx]
    part = SplitPartition(
        axis=axis,
        threshold=threshold,
        left_indices=left_idx,
        right_indices=right_idx,
        separability_gain=0.0,
        reward_variance=reward_variance(samples),
        mean_left=sum(left_r) / len(left_r),
        mean_right=sum(right_r) / len(right_r),
    )
    return part.__class__(
        **{**part.__dict__, "separability_gain": separability_gain(samples, part)}
    )


def _partition_categorical_exact(samples: list[RtSample]) -> SplitPartition | None:
    """One stimulus class vs the rest (equality on ``feature``, not substring)."""
    features = sorted({s.feature for s in samples if s.feature})
    best: SplitPartition | None = None
    for feat in features:
        left_idx = tuple(i for i, s in enumerate(samples) if s.feature == feat)
        right_idx = tuple(i for i, s in enumerate(samples) if s.feature != feat)
        part = _partition_from_indices(
            samples, axis=feat, threshold=feat, left_idx=left_idx, right_idx=right_idx
        )
        if part is None:
            continue
        if best is None or part.separability_gain > best.separability_gain:
            best = part
    return best


def _partition_token_axes(samples: list[RtSample]) -> SplitPartition | None:
    """Token presence axes for longer features (avoids 1-vs-(n−1) unique-string collapse)."""
    token_hits: dict[str, list[int]] = {}
    for i, sample in enumerate(samples):
        for tok in _feature_tokens(sample.feature):
            token_hits.setdefault(tok, []).append(i)

    best: SplitPartition | None = None
    for tok in sorted(token_hits):
        left_set = set(token_hits[tok])
        left_idx = tuple(sorted(left_set))
        right_idx = tuple(i for i in range(len(samples)) if i not in left_set)
        part = _partition_from_indices(
            samples, axis=f"token:{tok}", threshold=tok, left_idx=left_idx, right_idx=right_idx
        )
        if part is None:
            continue
        if best is None or part.separability_gain > best.separability_gain:
            best = part
    return best


def find_best_axis_partition(samples: list[RtSample]) -> SplitPartition | None:
    """Axis-aligned split: categorical equality or token axes (not ``feat in text``)."""
    if len(samples) < 4:
        return None
    if not any(s.feature for s in samples):
        mid = len(samples) // 2
        left_idx = tuple(range(mid))
        right_idx = tuple(range(mid, len(samples)))
        return _partition_from_indices(
            samples, axis="_index", threshold=str(mid), left_idx=left_idx, right_idx=right_idx
        )

    if is_categorical_feature_axis(samples):
        return _partition_categorical_exact(samples)
    return _partition_token_axes(samples)


def _welch_se(left: list[float], right: list[float]) -> float:
    n1, n2 = len(left), len(right)
    if n1 < 2 or n2 < 2:
        return float("inf")
    v1, v2 = _variance(left), _variance(right)
    return math.sqrt(v1 / n1 + v2 / n2)


def evaluate_split_guards(
    buffer: ConcernRtBuffer,
    concern_id: str,
    *,
    theta_h: float = 0.02,
    theta_sep: float = 0.15,
    n_min: int = 8,
    delta_min: float = 0.05,
    use_welch: bool = False,
    z_min: float = 1.96,
    temperature: float = 1.0,
    beta: float = 0.5,
    acceptance_sample: float | None = None,
) -> SplitGuardResult:
    samples = buffer.samples(concern_id)
    n = len(samples)
    if n < n_min:
        return SplitGuardResult(False, None, None, reason=f"n({concern_id})={n} < n_min={n_min}")

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

    gap = abs(partition.mean_left - partition.mean_right)
    left_r = [samples[i].r for i in partition.left_indices]
    right_r = [samples[i].r for i in partition.right_indices]
    if use_welch:
        se = _welch_se(left_r, right_r)
        if math.isfinite(se) and se > 1e-9:
            if gap < z_min * se:
                return SplitGuardResult(
                    False,
                    partition,
                    None,
                    reason=f"|r̄₁−r̄₂|={gap:.4f} < {z_min:.2f}·SE_w={z_min * se:.4f}",
                )
        elif gap < delta_min:
            return SplitGuardResult(
                False,
                partition,
                None,
                reason=f"|r̄₁−r̄₂|={gap:.4f} < δ (Welch n<2)",
            )
    elif gap < delta_min:
        return SplitGuardResult(
            False,
            partition,
            None,
            reason=f"|r̄₁−r̄₂|={gap:.4f} < δ",
        )

    delta = evaluate_delta_f(
        separability_gain=partition.separability_gain,
        temperature=temperature,
        beta=beta,
    )
    sample = acceptance_sample
    if sample is not None and not 0.0 <= sample < 1.0:
        raise ValueError(f"acceptance_sample must be in [0, 1); got {sample!r}")
    accepted = delta.accept if sample is None else sample < delta.acceptance_rate
    if not accepted:
        if sample is None:
            reason = "ΔF ≥ 0"
        else:
            reason = f"rewrite rejected u={sample:.4f} ≥ p={delta.acceptance_rate:.4f}"
        return SplitGuardResult(
            False,
            partition,
            delta,
            reason=reason,
            acceptance_sample=sample,
        )

    mode = "categorical" if is_categorical_feature_axis(samples) else "token"
    if sample is None:
        reason = f"accepted ({mode} axis={partition.axis})"
    else:
        reason = f"accepted ({mode} axis={partition.axis}, u={sample:.4f} < p={delta.acceptance_rate:.4f})"
    return SplitGuardResult(
        True,
        partition,
        delta,
        reason=reason,
        acceptance_sample=sample,
    )


__all__ = [
    "SplitGuardResult",
    "SplitPartition",
    "evaluate_split_guards",
    "find_best_axis_partition",
    "is_categorical_feature_axis",
    "reward_variance",
    "separability_gain",
]
