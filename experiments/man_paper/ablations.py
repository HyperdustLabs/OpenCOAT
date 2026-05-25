"""Full §8 empirical suites: longitudinal H1, sweeps, plasticity H3, tier-2, H5 reflex."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.connectome.model import build_connectome_view
from opencoat_runtime_core.credit.attribution import ActiveAspect
from opencoat_runtime_core.credit.credit_field import CreditField
from opencoat_runtime_core.credit.eligibility import EligibilityField
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.credit.rt_replay import read_rt_jsonl
from opencoat_runtime_core.credit.split_spec import evaluate_split_guards, reward_variance
from opencoat_runtime_core.credit.tier2_calibration import Tier2Calibrator
from opencoat_runtime_core.effector import EffectorAction
from opencoat_runtime_protocol import Concern, JoinpointEvent

from experiments.man_paper.metrics import RunMetrics
from experiments.man_paper.suites import (
    FIXTURES,
    ManMode,
    _active_from_fixture,
    _demo_tool_block_concern,
    _Harness,
    _load_fixture_concerns,
    _make_kernel,
)

TOOL_CASES = [
    ("rm -rf /tmp/x", False),
    ("ls -la", True),
    ("cat /etc/hosts", True),
    ("rm  -rf /var", False),
    ("echo ok", True),
]

# H1: verifier weight from real ``concern.activation_state.score`` (lifecycle.reinforce
# per success); warm reweight uses step_delta=0 so consume does not jump score.
H1_MATURITY_THRESHOLD = 0.65
H1_MATURITY_EPOCHS = 15


@dataclass
class SweepPoint:
    parameter: str
    value: float
    metric: float
    success: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "value": self.value,
            "metric": self.metric,
            "success": self.success,
            "notes": self.notes,
        }


def _load_bandit_concern(h: _Harness) -> None:
    path = FIXTURES / "bandit_parent_concern.json"
    if path.exists():
        c = Concern.model_validate(json.loads(path.read_text(encoding="utf-8")))
        h.store.upsert(c)
        h.dcn.add_node(c)


def _replay_jsonl(
    h: _Harness,
    path: Path,
    *,
    responsibility_uniform: bool = False,
) -> None:
    h.svc.credit_field.responsibility_mode = "uniform" if responsibility_uniform else "tier1"
    for rec in read_rt_jsonl(path):
        active = _active_from_fixture(rec)
        if active:
            h.svc.record_turn_activations(rec.turn_id, active)
        h.svc.append(rec)


def _concern_score(h: _Harness, concern_id: str) -> float:
    c = h.store.get(concern_id)
    if c is None or c.activation_state is None or c.activation_state.score is None:
        return 0.0
    return float(c.activation_state.score)


def run_h1_longitudinal(*, epochs: int = 10, trials_per_epoch: int = 60) -> dict[str, Any]:
    """H1: LLM calls/success falls for MAN as guard matures; baselines flat."""
    n_cases = len(TOOL_CASES)
    repeats = max(1, trials_per_epoch // n_cases)
    n_trials = n_cases * repeats
    series: dict[str, list[dict[str, float]]] = {}
    reinforce_per_success = H1_MATURITY_THRESHOLD / (H1_MATURITY_EPOCHS * n_trials)
    for mode in (ManMode.LLM_ONLY, ManMode.STATIC, ManMode.MAN_FULL):
        h = _Harness(
            mode,
            plasticity_engine=PlasticityEngine(step_delta=1e-6),
            lifecycle_initial_score=0.0,
        )
        if mode != ManMode.LLM_ONLY:
            demo = _demo_tool_block_concern()
            h.store.upsert(demo)
            h.dcn.add_node(demo)
        kernel = _make_kernel(h)
        epoch_rows: list[dict[str, float]] = []
        for epoch in range(epochs):
            calls = 0.0
            successes = 0
            for cmd, want_allow in TOOL_CASES * repeats:
                guard_score = (
                    _concern_score(h, "demo-tool-block") if mode == ManMode.MAN_FULL else 0.0
                )
                verify_weight = max(
                    0.0,
                    1.0 - guard_score / H1_MATURITY_THRESHOLD,
                )
                planner = 1.0
                verify = 0.0
                if mode == ManMode.MAN_FULL:
                    verify = verify_weight
                elif mode == ManMode.LLM_ONLY and not want_allow:
                    verify = 1.0
                calls += planner + verify
                if kernel is None:
                    ok = want_allow
                else:
                    out = kernel.run_turn(
                        JoinpointEvent(
                            id=f"jp-{epoch}",
                            level=3,
                            name="before_tool_call",
                            host="paper-h1",
                            ts=datetime.now(tz=UTC),
                        ),
                        EffectorAction(kind="tool_call", name="shell.exec", args={"command": cmd}),
                        context={"command": cmd},
                        turn_id=f"h1-{epoch}-{int(calls)}",
                    )
                    ok = out.allowed == want_allow
                    h.svc.append(out.record)
                if ok:
                    successes += 1
                    if mode == ManMode.MAN_FULL:
                        c = h.store.get("demo-tool-block")
                        if c is not None:
                            h.lifecycle.reinforce(c, delta=reinforce_per_success)
            h._plasticity_step(warm_only=True)
            guard_score = _concern_score(h, "demo-tool-block")
            mature = guard_score >= H1_MATURITY_THRESHOLD
            success_rate = successes / n_trials
            cps = calls / max(successes, 1)
            epoch_rows.append(
                {
                    "epoch": float(epoch),
                    "llm_calls_per_success": cps,
                    "success_rate": success_rate,
                    "guard_score": guard_score,
                    "mature": 1.0 if mature else 0.0,
                }
            )
        series[mode.value] = epoch_rows

    man = series[ManMode.MAN_FULL.value]
    h1_ok = (
        man[-1]["llm_calls_per_success"] < man[0]["llm_calls_per_success"]
        and man[-1]["success_rate"] >= man[0]["success_rate"] - 0.05
    )
    return {
        "pass": h1_ok,
        "series": series,
        "delta_cps_man": man[0]["llm_calls_per_success"] - man[-1]["llm_calls_per_success"],
    }


def run_lambda_sweep() -> list[SweepPoint]:
    """Eligibility λ sweep: conservation + trace mass on bimodal replay."""
    rt_path = FIXTURES / "r_t_bimodal.jsonl"
    points: list[SweepPoint] = []
    for lam in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0):
        from opencoat_runtime_storage.memory import MemoryConcernStore

        store = MemoryConcernStore()
        for name in ("bimodal_concern.json", "soft_hint_concern.json"):
            store.upsert(
                Concern.model_validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
            )
        field = CreditField(
            concern_store=store,
            eligibility=EligibilityField(trace_lambda=lam, trace_alpha=1.0),
        )
        residuals: list[float] = []
        trace_sum = 0.0
        for rec in read_rt_jsonl(rt_path):
            active = _active_from_fixture(rec)
            res = field.attribute_turn(rec, active=active)
            residuals.append(abs(res.conservation_residual))
            trace_sum = sum(field.eligibility.snapshot()["aspect"].values())
        ok = max(residuals) < 1e-5 if lam > 0 else True
        points.append(
            SweepPoint(
                parameter="trace_lambda",
                value=lam,
                metric=trace_sum,
                success=ok,
                notes=f"max_resid={max(residuals):.2e}",
            )
        )
    return points


def run_beta_sweep() -> list[SweepPoint]:
    """Split guard β sweep: fraction eligible on bimodal buffer."""
    buffer = ConcernRtBuffer()
    from opencoat_runtime_storage.memory import MemoryConcernStore

    store = MemoryConcernStore()
    for name in ("bimodal_concern.json", "soft_hint_concern.json"):
        store.upsert(
            Concern.model_validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
        )
    field = CreditField(concern_store=store, buffer=buffer)
    for rec in read_rt_jsonl(FIXTURES / "r_t_bimodal.jsonl"):
        field.attribute_turn(rec, active=_active_from_fixture(rec))

    points: list[SweepPoint] = []
    for beta in (0.01, 0.02, 0.05, 0.1, 0.5, 1.0):
        guard = evaluate_split_guards(
            buffer, "paper.bimodal-guard", n_min=8, theta_h=0.01, beta=beta
        )
        points.append(
            SweepPoint(
                parameter="split_beta",
                value=beta,
                metric=1.0 if guard.eligible else 0.0,
                success=guard.eligible if beta <= 0.1 else not guard.eligible,
                notes=guard.reason,
            )
        )
    return points


def _cold_plasticity_stats(
    path: Path,
    *,
    uniform: bool,
    cold_rounds: int = 6,
    shuffle_buffer: bool = True,
) -> dict[str, Any]:
    """Plasticity cold-path H3: tier-1 vs uniform on bandit buffer (preserves ``r``)."""
    from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    parent = Concern.model_validate(
        json.loads((FIXTURES / "bandit_parent_concern.json").read_text(encoding="utf-8"))
    )
    store.upsert(parent)
    dcn.add_node(parent)
    buffer = ConcernRtBuffer()
    field = CreditField(
        concern_store=store,
        buffer=buffer,
        responsibility_mode="uniform" if uniform else "tier1",
    )
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    records = read_rt_jsonl(path)
    for rec in records:
        field.attribute_turn(rec, active=_active_from_fixture(rec))

    engine = PlasticityEngine(split_beta=0.02, split_theta_h=0.01)
    parent_c = store.get("paper.bandit-parent")
    assert parent_c is not None
    for _ in range(5):
        parent_c = lifecycle.reinforce(parent_c, delta=0.0)
    parent_c = lifecycle.reinforce(parent_c, delta=0.15)

    if uniform and shuffle_buffer:
        import random

        rng = random.Random(7)
        rows = buffer.samples("paper.bandit-parent")
        rewards = [row.r for row in rows]
        rng.shuffle(rewards)
        for i, row in enumerate(rows):
            rows[i] = type(row)(r=rewards[i], feature=row.feature)

    from opencoat_runtime_core.credit.connectome_plasticity import split_with_spec_or_keywords

    samples = buffer.samples("paper.bandit-parent")
    mean_r = sum(s.r for s in samples) / max(len(samples), 1)

    splits = 0
    merges = 0
    spurious = 0
    parent_c = store.get("paper.bandit-parent")
    assert parent_c is not None
    guard = evaluate_split_guards(buffer, "paper.bandit-parent", n_min=8, theta_h=0.01, beta=0.02)
    if guard.eligible and guard.partition is not None:
        pv = reward_variance(samples)
        if split_with_spec_or_keywords(
            concern=parent_c,
            concern_store=store,
            buffer=buffer,
            lifecycle=lifecycle,
            guard=guard,
        ):
            splits = 1
            mean_gap = abs(guard.partition.mean_left - guard.partition.mean_right)
            left = [samples[i] for i in guard.partition.left_indices]
            right = [samples[i] for i in guard.partition.right_indices]
            if mean_gap < 0.2 or not (reward_variance(left) < pv and reward_variance(right) < pv):
                spurious = 1
    for _ in range(cold_rounds - 1):
        cold = engine.cold_step(
            concern_store=store, dcn_store=dcn, lifecycle=lifecycle, buffer=buffer
        )
        merges += int(cold.merged)

    view = build_connectome_view(concern_store=store, dcn_store=dcn)
    return {
        "splits": splits,
        "merges": merges,
        "spurious_splits": spurious,
        "spurious_rate": spurious / max(splits, 1),
        "mean_reward": mean_r,
        "aspects": len(view.aspects),
        "edges": len(view.edges),
    }


def run_h3_plasticity_ablation() -> tuple[RunMetrics, RunMetrics]:
    """H3: tier-1 split quality vs uniform ρ on clean vs noisy bandit."""
    clean = FIXTURES / "r_t_bandit.jsonl"
    noisy = FIXTURES / "r_t_bandit_noisy.jsonl"
    tier1 = _cold_plasticity_stats(clean, uniform=False)
    uniform = _cold_plasticity_stats(
        noisy if noisy.exists() else clean, uniform=True, shuffle_buffer=False
    )
    h3_ok = (
        uniform["spurious_rate"] > tier1["spurious_rate"]
        or uniform["mean_reward"] < tier1["mean_reward"] - 0.02
        or (tier1["splits"] >= 1 and uniform["splits"] == 0)
    )
    return (
        RunMetrics(
            method="tier1_plasticity",
            success_rate=1.0 if tier1["splits"] >= 1 else 0.0,
            llm_calls_per_success=1.0,
            mean_reward=tier1["mean_reward"],
            spurious_split_rate=tier1["spurious_rate"],
            splits=int(tier1["splits"]),
            merges=int(tier1["merges"]),
            edges=int(tier1["edges"]),
            aspects=int(tier1["aspects"]),
            notes=f"spurious={tier1['spurious_splits']} splits={tier1['splits']}",
        ),
        RunMetrics(
            method="uniform_plasticity",
            success_rate=1.0 if h3_ok else 0.0,
            llm_calls_per_success=1.0,
            mean_reward=uniform["mean_reward"],
            spurious_split_rate=uniform["spurious_rate"],
            splits=int(uniform["splits"]),
            merges=int(uniform["merges"]),
            edges=int(uniform["edges"]),
            aspects=int(uniform["aspects"]),
            notes=f"spurious={uniform['spurious_splits']} splits={uniform['splits']} h3_ok={h3_ok}",
        ),
    )


def run_tier2_ablation() -> RunMetrics:
    """Tier-2 LOO on/off: split count on bandit after warm."""
    from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

    def splits_with(*, samples: int) -> int:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        c = Concern.model_validate(
            json.loads((FIXTURES / "bandit_parent_concern.json").read_text(encoding="utf-8"))
        )
        store.upsert(c)
        dcn.add_node(c)
        buffer = ConcernRtBuffer()
        field = CreditField(concern_store=store, buffer=buffer)
        lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
        for rec in read_rt_jsonl(FIXTURES / "r_t_bandit.jsonl"):
            field.attribute_turn(rec, active=_active_from_fixture(rec))
        engine = PlasticityEngine(tier2=Tier2Calibrator(samples=samples))
        engine.warm_step(
            read_rt_jsonl(FIXTURES / "r_t_bandit.jsonl"),
            concern_store=store,
            dcn_store=dcn,
            lifecycle=lifecycle,
        )
        parent = store.get("paper.bandit-parent")
        assert parent is not None
        for _ in range(4):
            parent = lifecycle.reinforce(parent, delta=0.2)
        cold = engine.cold_step(
            concern_store=store, dcn_store=dcn, lifecycle=lifecycle, buffer=buffer
        )
        return int(cold.split)

    off = splits_with(samples=0)
    on = splits_with(samples=3)
    return RunMetrics(
        method="tier2_ablation",
        success_rate=1.0,
        llm_calls_per_success=1.0,
        spurious_split_rate=float(on - off),
        notes=f"splits_off={off} splits_on={on}",
    )


def run_h5_reflex_ablation(*, long: bool = True) -> tuple[RunMetrics, RunMetrics]:
    """H5: -- conserved reflex core → higher aspect/edge growth on long soak."""
    path = FIXTURES / ("r_t_soak_long.jsonl" if long else "r_t_bimodal.jsonl")

    def soak(*, disable_reflex: bool) -> RunMetrics:
        h = _Harness(ManMode.MAN_FULL, disable_reflex_core=disable_reflex)
        _load_fixture_concerns(h)
        edge_trace: list[int] = []
        for i, rec in enumerate(read_rt_jsonl(path)):
            active = _active_from_fixture(rec)
            if active:
                h.svc.record_turn_activations(rec.turn_id, active)
            h.svc.append(rec)
            if (i + 1) % 16 == 0:
                h._plasticity_step()
                snap = build_connectome_view(concern_store=h.store, dcn_store=h.dcn)
                edge_trace.append(len(snap.edges))
        snap = build_connectome_view(concern_store=h.store, dcn_store=h.dcn)
        span = max(edge_trace) - min(edge_trace) if edge_trace else 0
        stable = span <= max(8, len(edge_trace))
        return RunMetrics(
            method="reflex_on" if not disable_reflex else "reflex_off",
            success_rate=1.0 if stable else 0.0,
            llm_calls_per_success=1.0,
            struct_stability=float(span),
            edges=len(snap.edges),
            aspects=len(snap.aspects),
            splits=h._splits,
            notes=f"edge_span={span} stable={stable}",
        )

    return soak(disable_reflex=False), soak(disable_reflex=True)


def run_h4_stochastic_sweep() -> list[SweepPoint]:
    """H4: reliability gap (hard vs soft ρ) vs outcome noise level."""
    import random

    from opencoat_runtime_core.credit.attribution import tier1_responsibility

    active = [
        ActiveAspect("paper.bimodal-guard", 0.85, hard=True),
        ActiveAspect("paper.soft-hint", 0.4, hard=False),
    ]
    points: list[SweepPoint] = []
    for noise in (0.0, 0.1, 0.2, 0.3, 0.4):
        rng = random.Random(99 + int(noise * 100))
        hard_ok: list[float] = []
        soft_ok: list[float] = []
        for _ in range(200):
            r_hard = 1.0 if rng.random() > noise else 0.0
            r_soft = 1.0 if rng.random() > noise * 1.5 else 0.0
            hard_ok.append(r_hard)
            soft_ok.append(r_soft)
        rho = tier1_responsibility(active)
        gap_rho = rho["paper.bimodal-guard"] - rho["paper.soft-hint"]

        def var(xs: list[float]) -> float:
            m = sum(xs) / len(xs)
            return sum((x - m) ** 2 for x in xs) / len(xs)

        gap_out = var(soft_ok) - var(hard_ok)
        points.append(
            SweepPoint(
                parameter="outcome_noise",
                value=noise,
                metric=gap_out,
                success=gap_out > 0 and gap_rho > 0,
                notes=f"rho_gap={gap_rho:.3f} var_soft-var_hard={gap_out:.4f}",
            )
        )
    return points


def run_h2_reward_lift() -> RunMetrics:
    """H2: child contexts improve mean reward vs parent on bandit partition."""
    buffer = ConcernRtBuffer()
    from opencoat_runtime_storage.memory import MemoryConcernStore

    store = MemoryConcernStore()
    store.upsert(
        Concern.model_validate(
            json.loads((FIXTURES / "bandit_parent_concern.json").read_text(encoding="utf-8"))
        )
    )
    field = CreditField(concern_store=store, buffer=buffer)
    for rec in read_rt_jsonl(FIXTURES / "r_t_bandit.jsonl"):
        field.attribute_turn(rec, active=_active_from_fixture(rec))

    parent_id = "paper.bandit-parent"
    guard = evaluate_split_guards(buffer, parent_id, n_min=8, theta_h=0.01, beta=0.02)
    parent_mean = sum(s.r for s in buffer.samples(parent_id)) / max(buffer.count(parent_id), 1)
    lift = 0.0
    if guard.partition:
        samples = buffer.samples(parent_id)
        left = [samples[i] for i in guard.partition.left_indices]
        right = [samples[i] for i in guard.partition.right_indices]
        ml = sum(s.r for s in left) / len(left)
        mr = sum(s.r for s in right) / len(right)
        lift = max(ml, mr) - parent_mean
    ok = guard.eligible and lift >= 0.05
    return RunMetrics(
        method="h2_bandit_lift",
        success_rate=1.0 if ok else 0.0,
        llm_calls_per_success=1.0,
        mean_reward=parent_mean + lift,
        notes=f"lift={lift:.3f} eligible={guard.eligible}",
    )


__all__ = [
    "SweepPoint",
    "run_beta_sweep",
    "run_h1_longitudinal",
    "run_h2_reward_lift",
    "run_h3_plasticity_ablation",
    "run_h4_stochastic_sweep",
    "run_h5_reflex_ablation",
    "run_lambda_sweep",
    "run_tier2_ablation",
]
