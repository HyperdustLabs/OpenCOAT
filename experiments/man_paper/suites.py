"""Paper §8 experiment suites runnable with demo concerns (no external benchmark)."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import mkstemp
from typing import Any

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.connectome.model import build_connectome_view
from opencoat_runtime_core.credit.attribution import ActiveAspect
from opencoat_runtime_core.credit.credit_field import CreditField
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.credit.rt_replay import (
    read_rt_jsonl,
    replay_credit_conservation,
    replay_rt_jsonl,
)
from opencoat_runtime_core.credit.split_spec import evaluate_split_guards, reward_variance
from opencoat_runtime_core.effector import EffectorAction, EffectorKernel
from opencoat_runtime_protocol import (
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    JoinpointEvent,
    PointcutDef,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

from experiments.man_paper.metrics import RunMetrics, tier1_replay_hash

FIXTURES = (
    Path(__file__).resolve().parents[2] / "packages/opencoat-runtime/tests/fixtures/morphogenetic"
)


class ManMode(StrEnum):
    MAN_FULL = "man_full"
    STATIC = "static_aspect_graph"
    WEIGHT_ONLY = "weight_only_plasticity"
    FIXED_PROMPT = "fixed_hand_prompt"
    LLM_ONLY = "llm_only"


@dataclass
class _Harness:
    mode: ManMode
    responsibility_uniform: bool = False
    disable_reflex_core: bool = False
    plasticity_engine: PlasticityEngine | None = None
    lifecycle_initial_score: float | None = None

    def __post_init__(self) -> None:
        self.store = MemoryConcernStore()
        self.dcn = MemoryDCNStore()
        self.engine = self.plasticity_engine or PlasticityEngine()
        lc_kwargs: dict[str, float] = {}
        if self.lifecycle_initial_score is not None:
            lc_kwargs["initial_score"] = self.lifecycle_initial_score
        self.lifecycle = ConcernLifecycleManager(
            concern_store=self.store, dcn_store=self.dcn, **lc_kwargs
        )
        fd, rt_path = mkstemp(prefix="man_paper_r_t_", suffix=".jsonl")
        os.close(fd)
        self.svc = RtPlasticityService(
            concern_store=self.store,
            dcn_store=self.dcn,
            path=Path(rt_path),
            engine=self.engine,
        )
        if self.responsibility_uniform:
            self.svc.credit_field.responsibility_mode = "uniform"
        self._splits = 0
        self._merges = 0
        self._conservation: list[float] = []

    def _plasticity_step(self, *, warm_only: bool = False) -> dict[str, int]:
        if self.mode == ManMode.STATIC:
            return {}
        warm = self.svc.consume(max_records=None)
        if self.mode == ManMode.WEIGHT_ONLY or warm_only:
            return warm.as_dict()
        cold = self.svc.cold_step()
        self._splits += int(cold.get("split", 0))
        self._merges += int(cold.get("merged", 0))
        out = warm.as_dict()
        for k, v in cold.items():
            out[f"cold_{k}"] = v
        return out

    def _snapshot(self) -> dict[str, Any]:
        view = build_connectome_view(concern_store=self.store, dcn_store=self.dcn)
        return {
            "aspects": len(view.aspects),
            "edges": len(view.edges),
            "eligibility": self.svc.credit_field.eligibility.snapshot(),
        }


def _demo_tool_block_concern() -> Concern:
    return Concern(
        id="demo-tool-block",
        name="Demo tool block",
        pointcuts=[
            PointcutDef(
                id="pc-tool",
                expression="before_tool_call()",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["rm -rf", "rm  -rf"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-block",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-tool",
                content="Refusing destructive shell command.",
                template=AdviceType.TOOL_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.TOOL_LEVEL,
                    target="tool_call.arguments",
                    priority=0.9,
                ),
            ),
        ],
    )


def _load_fixture_concerns(h: _Harness) -> None:
    for name in ("bimodal_concern.json", "soft_hint_concern.json"):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        c = Concern.model_validate(data)
        if h.disable_reflex_core and c.reflex:
            continue
        h.store.upsert(c)
        with suppress(Exception):
            h.dcn.add_node(c)


def _load_fixture_into_store(store: MemoryConcernStore, dcn: MemoryDCNStore) -> None:
    for name in ("bimodal_concern.json", "soft_hint_concern.json"):
        c = Concern.model_validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
        store.upsert(c)
        with suppress(Exception):
            dcn.add_node(c)


def _make_kernel(h: _Harness) -> EffectorKernel | None:
    if h.mode == ManMode.LLM_ONLY:
        return None
    from opencoat_runtime_core.advice import AdviceGenerator
    from opencoat_runtime_core.config import RuntimeConfig
    from opencoat_runtime_core.coordinator import ConcernCoordinator
    from opencoat_runtime_core.llm import StubLLMClient
    from opencoat_runtime_core.loops.joinpoint_pipeline import JoinpointPipeline
    from opencoat_runtime_core.pointcut.matcher import PointcutMatcher
    from opencoat_runtime_core.weaving import ConcernWeaver

    cfg = RuntimeConfig()
    pipeline = JoinpointPipeline(
        config=cfg,
        concern_store=h.store,
        dcn_store=h.dcn,
        matcher=PointcutMatcher(),
        coordinator=ConcernCoordinator(budgets=cfg.budgets),
        weaver=ConcernWeaver(budgets=cfg.budgets),
        advice_plugin=AdviceGenerator(llm=StubLLMClient()),
    )
    pipeline.set_coactivation_recorder(h.svc.record_coactivation)
    pipeline.set_activation_recorder(h.svc.record_turn_activations)
    pipeline.set_eligibility_field(h.svc.credit_field.eligibility)
    return EffectorKernel(pipeline=pipeline, concern_store=h.store)


def run_demo_tool_suite(mode: ManMode, *, responsibility_uniform: bool = False) -> RunMetrics:
    """(ii) Verifiable tool guard — deny rm, allow ls (H1/H4 proxy)."""
    h = _Harness(mode, responsibility_uniform=responsibility_uniform)
    if mode != ManMode.LLM_ONLY:
        demo = _demo_tool_block_concern()
        h.store.upsert(demo)
        h.dcn.add_node(demo)

    kernel = _make_kernel(h)
    jp = JoinpointEvent(
        id="jp-demo",
        level=3,
        name="before_tool_call",
        host="paper-exp",
        ts=datetime.now(tz=UTC),
    )
    cases = [("rm -rf /tmp/x", False), ("ls -la", True)] * 20
    successes = 0
    llm_calls = 0
    hard_outcomes: list[float] = []
    for cmd, want_allow in cases:
        llm_calls += 1
        if kernel is None:
            ok = want_allow
        else:
            out = kernel.run_turn(
                jp,
                EffectorAction(kind="tool_call", name="shell.exec", args={"command": cmd}),
                context={"command": cmd},
                turn_id=f"demo-{llm_calls}",
            )
            ok = out.allowed == want_allow
            h.svc.append(out.record)
            hard_outcomes.append(1.0 if ok else 0.0)
        if ok:
            successes += 1
        if llm_calls % 8 == 0:
            h._plasticity_step()

    h._plasticity_step()
    snap = h._snapshot()
    spurious = h._merges / max(h._splits, 1) if h._splits else 0.0
    rel_gap = 1.0 - (sum(hard_outcomes) / len(hard_outcomes)) if hard_outcomes else None
    return RunMetrics(
        method=mode.value,
        success_rate=successes / len(cases),
        llm_calls_per_success=llm_calls / max(successes, 1),
        reliability_gap=rel_gap,
        struct_stability=float(snap["edges"]),
        spurious_split_rate=spurious,
        edges=int(snap["edges"]),
        aspects=int(snap["aspects"]),
        splits=h._splits,
        merges=h._merges,
    )


def _active_from_fixture(rec: RtRecord) -> list[ActiveAspect]:
    from opencoat_runtime_core.credit.rt_replay import _active_from_record

    return _active_from_record(rec)


def run_bandit_suite(mode: ManMode, *, responsibility_uniform: bool = False) -> RunMetrics:
    """(i) Bimodal fixture — H2 split variance (matches paper validation test)."""
    from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer

    h = _Harness(mode, responsibility_uniform=responsibility_uniform)
    _load_fixture_concerns(h)
    parent_id = "paper.bimodal-guard"
    buffer = ConcernRtBuffer()

    for rec in read_rt_jsonl(FIXTURES / "r_t_bimodal.jsonl"):
        active = _active_from_fixture(rec)
        field = CreditField(
            concern_store=h.store,
            buffer=buffer,
            responsibility_mode="uniform" if h.responsibility_uniform else "tier1",
        )
        result = field.attribute_turn(rec, active=active)
        h._conservation.append(abs(result.conservation_residual))

    parent_var = reward_variance(buffer.samples(parent_id))
    guard = evaluate_split_guards(buffer, parent_id, n_min=8, theta_h=0.01, beta=0.02)
    child_vars: list[float] = []
    if guard.partition:
        samples = buffer.samples(parent_id)
        left = [samples[i] for i in guard.partition.left_indices]
        right = [samples[i] for i in guard.partition.right_indices]
        child_vars = [reward_variance(left), reward_variance(right)]

    if mode != ManMode.STATIC:
        h._plasticity_step()

    snap = h._snapshot()
    h2_ok = (
        guard.eligible
        and guard.partition is not None
        and child_vars
        and all(v < parent_var for v in child_vars)
    )
    return RunMetrics(
        method=mode.value,
        success_rate=1.0 if h2_ok else 0.0,
        llm_calls_per_success=1.0,
        spurious_split_rate=h._merges / max(h._splits, 1) if h._splits else 0.0,
        edges=int(snap["edges"]),
        aspects=int(snap["aspects"]),
        splits=h._splits,
        merges=h._merges,
        conservation_max_abs_residual=max(h._conservation) if h._conservation else 0.0,
        notes=f"H2_pass={h2_ok} parent_var={parent_var:.4f} child_vars={child_vars}",
    )


def run_soak_suite(mode: ManMode) -> RunMetrics:
    """(iii) Long-horizon replay — H5 stability on ``r_t_soak_long.jsonl`` when present."""
    h = _Harness(mode)
    _load_fixture_concerns(h)
    soak_path = FIXTURES / "r_t_soak_long.jsonl"
    rt_path = soak_path if soak_path.exists() else FIXTURES / "r_t_bimodal.jsonl"
    if not rt_path.exists():
        raise FileNotFoundError(rt_path)
    step_interval = 32 if rt_path == soak_path else 8

    edge_trace: list[int] = []
    aspect_trace: list[int] = []
    rewards: list[float] = []

    for i, rec in enumerate(read_rt_jsonl(rt_path)):
        active = [
            ActiveAspect(a["concern_id"], float(a.get("activation_score", 1)), bool(a.get("hard")))
            for a in (rec.signal.payload or {}).get("active_aspects", [])
            if isinstance(a, dict)
        ]
        if active:
            h.svc.record_turn_activations(rec.turn_id, active)
        h.svc.append(rec)
        rewards.append(rec.r)
        if (i + 1) % step_interval == 0:
            h._plasticity_step()
            snap = h._snapshot()
            edge_trace.append(int(snap["edges"]))
            aspect_trace.append(int(snap["aspects"]))

    snap = h._snapshot()
    edge_span = max(edge_trace) - min(edge_trace) if edge_trace else 0
    reward_span = max(rewards) - min(rewards) if rewards else 0.0
    n_rows = len(rewards)
    stable = edge_span <= max(8, len(edge_trace)) and reward_span <= 1.5

    return RunMetrics(
        method=mode.value,
        success_rate=1.0 if stable else 0.0,
        llm_calls_per_success=1.0,
        struct_stability=float(edge_span),
        edges=int(snap["edges"]),
        aspects=int(snap["aspects"]),
        splits=h._splits,
        merges=h._merges,
        notes=(
            f"H5_stable={stable} edge_span={edge_span} reward_span={reward_span} "
            f"rows={n_rows} fixture={rt_path.name}"
        ),
    )


def run_replay_suite() -> RunMetrics:
    """Tier-1 replay determinism + conservation on fixture."""
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    _load_fixture_into_store(store, dcn)
    residuals = replay_credit_conservation(FIXTURES / "r_t_bimodal.jsonl", concern_store=store)

    def state_hash() -> dict[str, Any]:
        scores1 = replay_rt_jsonl(
            FIXTURES / "r_t_bimodal.jsonl",
            concern_store=MemoryConcernStore(),
            dcn_store=MemoryDCNStore(),
            cold=True,
        )
        scores2 = replay_rt_jsonl(
            FIXTURES / "r_t_bimodal.jsonl",
            concern_store=MemoryConcernStore(),
            dcn_store=MemoryDCNStore(),
            cold=True,
        )
        return {"scores1": scores1, "scores2": scores2}

    sh = state_hash()
    det = sh["scores1"] == sh["scores2"]
    return RunMetrics(
        method="tier1_replay",
        success_rate=1.0 if det else 0.0,
        llm_calls_per_success=1.0,
        conservation_max_abs_residual=max(abs(r) for r in residuals),
        replay_hash=tier1_replay_hash(sh["scores1"]),
        notes=f"deterministic={det} max_residual={max(abs(r) for r in residuals):.2e}",
    )


def run_h3_ablation() -> tuple[RunMetrics, RunMetrics]:
    """Tier-1 vs uniform ρ spread on bimodal activations (H3 proxy)."""
    from opencoat_runtime_core.credit.attribution import (
        tier1_responsibility,
        uniform_responsibility,
    )

    active = [
        ActiveAspect("paper.bimodal-guard", 0.85, hard=True),
        ActiveAspect("paper.soft-hint", 0.4, hard=False),
    ]
    t1 = tier1_responsibility(active)
    uni = uniform_responsibility(active)
    spread_t1 = t1["paper.bimodal-guard"] - t1["paper.soft-hint"]
    spread_uni = abs(uni["paper.bimodal-guard"] - uni["paper.soft-hint"])
    tier1_m = RunMetrics(
        method="tier1_rho",
        success_rate=1.0 if spread_t1 > spread_uni else 0.0,
        llm_calls_per_success=1.0,
        spurious_split_rate=spread_t1,
        notes=f"hard_minus_soft_rho={spread_t1:.4f} uniform_spread={spread_uni:.4f}",
    )
    uniform_m = RunMetrics(
        method="uniform_rho",
        success_rate=1.0 if spread_uni < 1e-9 else 0.0,
        llm_calls_per_success=1.0,
        spurious_split_rate=spread_uni,
        notes="uniform baseline",
    )
    return tier1_m, uniform_m


def run_h4_proxy() -> RunMetrics:
    """Hard vs soft: tier-1 ρ favors hard aspect (paper validation test)."""
    from opencoat_runtime_core.credit.attribution import tier1_responsibility

    active = [
        ActiveAspect("hard-a", 0.9, hard=True),
        ActiveAspect("soft-b", 0.9, hard=False),
    ]
    rho = tier1_responsibility(active)
    gap = rho["hard-a"] - rho["soft-b"]
    return RunMetrics(
        method="H4_hard_vs_soft",
        success_rate=1.0 if gap > 0 else 0.0,
        llm_calls_per_success=1.0,
        reliability_gap=gap,
        notes=f"rho_hard={rho['hard-a']:.4f} rho_soft={rho['soft-b']:.4f}",
    )


__all__ = [
    "ManMode",
    "run_bandit_suite",
    "run_demo_tool_suite",
    "run_h3_ablation",
    "run_h4_proxy",
    "run_replay_suite",
    "run_soak_suite",
]
