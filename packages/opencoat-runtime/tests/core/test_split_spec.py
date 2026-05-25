"""Split axis: categorical stimulus id vs free-text feature collapse."""

from __future__ import annotations

from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer, RtSample
from opencoat_runtime_core.credit.split_spec import (
    evaluate_split_guards,
    find_best_axis_partition,
    is_categorical_feature_axis,
)


def _samples(features: list[str], rewards: list[float]) -> list[RtSample]:
    return [RtSample(feature=f, r=r) for f, r in zip(features, rewards, strict=True)]


def test_categorical_scenario_axis_splits_cleanly() -> None:
    feats = ["ct-a"] * 4 + ["ct-b"] * 4
    rs = [0.0] * 4 + [1.0] * 4
    samples = _samples(feats, rs)
    assert is_categorical_feature_axis(samples)
    part = find_best_axis_partition(samples)
    assert part is not None
    assert part.separability_gain > 0.1
    buf = ConcernRtBuffer()
    for f, r in zip(feats, rs, strict=True):
        buf.append("c", r=r, feature=f)
    guard = evaluate_split_guards(buf, "c", n_min=8, use_welch=True, theta_h=0.01, beta=0.01)
    assert guard.eligible, guard.reason


def test_split_guard_stochastic_accepts_uphill_rewrite() -> None:
    feats = ["ct-a"] * 4 + ["ct-b"] * 4
    rs = [0.0] * 4 + [1.0] * 4
    buf = ConcernRtBuffer()
    for f, r in zip(feats, rs, strict=True):
        buf.append("c", r=r, feature=f)

    rejected = evaluate_split_guards(
        buf,
        "c",
        n_min=8,
        use_welch=True,
        theta_h=0.01,
        beta=0.1,
        temperature=1.0,
        acceptance_sample=0.9,
    )
    assert rejected.delta_f is not None
    assert rejected.delta_f.delta_f > 0
    assert not rejected.eligible
    assert "rewrite rejected" in rejected.reason

    accepted = evaluate_split_guards(
        buf,
        "c",
        n_min=8,
        use_welch=True,
        theta_h=0.01,
        beta=0.1,
        temperature=1.0,
        acceptance_sample=0.1,
    )
    assert accepted.delta_f is not None
    assert accepted.delta_f.delta_f > 0
    assert accepted.eligible, accepted.reason
    assert accepted.acceptance_sample == 0.1


def test_unique_free_text_buffer_rejects_or_weak_guard() -> None:
    """High-cardinality LLM-style rows: split must not rely on 1-vs-(n−1) substring collapse."""
    feats = [f"assistant paragraph {i} with unique tokens uid{i}" for i in range(12)]
    rs = [0.0 if i % 2 == 0 else 1.0 for i in range(12)]
    assert not is_categorical_feature_axis(_samples(feats, rs))
    buf = ConcernRtBuffer()
    for f, r in zip(feats, rs, strict=True):
        buf.append("c", r=r, feature=f)
    guard = evaluate_split_guards(buf, "c", n_min=8, use_welch=True, theta_h=0.01, beta=0.01)
    assert not guard.eligible
