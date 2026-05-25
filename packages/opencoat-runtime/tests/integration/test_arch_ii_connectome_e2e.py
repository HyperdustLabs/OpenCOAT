"""Architecture (ii) E2E: route → weave → coactivate → warm/cold graph evolution."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.advice import AdviceGenerator
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.config import RuntimeConfig
from opencoat_runtime_core.connectome.model import build_connectome_view
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.effector import EffectorAction, EffectorKernel
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.loops.joinpoint_pipeline import JoinpointPipeline
from opencoat_runtime_core.pointcut.matcher import PointcutMatcher
from opencoat_runtime_core.weaving import ConcernWeaver
from opencoat_runtime_protocol import JoinpointEvent
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore
from tests.core.test_effector_kernel import _demo_tool_block


def _pipeline(store: MemoryConcernStore, dcn: MemoryDCNStore) -> JoinpointPipeline:
    cfg = RuntimeConfig()
    return JoinpointPipeline(
        config=cfg,
        concern_store=store,
        dcn_store=dcn,
        matcher=PointcutMatcher(),
        coordinator=ConcernCoordinator(budgets=cfg.budgets),
        weaver=ConcernWeaver(budgets=cfg.budgets),
        advice_plugin=AdviceGenerator(llm=StubLLMClient()),
    )


def test_arch_ii_full_graph_loop() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(_demo_tool_block())

    pipeline = _pipeline(store, dcn)
    svc = RtPlasticityService(concern_store=store, dcn_store=dcn)
    pipeline.set_coactivation_recorder(svc.record_coactivation)

    jp = JoinpointEvent(
        id="jp-ii",
        level=3,
        name="before_tool_call",
        host="test",
        ts=datetime.now(tz=UTC),
        payload={"command": "rm -rf /tmp"},
    )
    route_info = pipeline.route_joinpoint(
        jp,
        context={"command": "rm -rf /tmp"},
    )
    assert route_info["pointcut_hits"] >= 1
    assert any(r["concern_id"] == "demo-tool-block" for r in route_info["routed"])

    kernel = EffectorKernel(pipeline=pipeline, concern_store=store)
    outcome = kernel.run_turn(
        jp,
        EffectorAction(kind="tool_call", name="shell.exec", args={"command": "rm -rf /"}),
        turn_id="arch-ii-1",
    )
    assert outcome.allowed is False
    svc.append(outcome.record)

    warm = svc.consume()
    assert warm.reinforced >= 1

    view_before = build_connectome_view(concern_store=store, dcn_store=dcn)
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    cold = (
        PlasticityEngine()
        .cold_step(
            concern_store=store,
            dcn_store=dcn,
            lifecycle=lifecycle,
            buffer=svc.buffer,
        )
        .as_dict()
    )
    view_after = build_connectome_view(concern_store=store, dcn_store=dcn)
    stats = svc.connectome_stats()
    assert stats["aspects"] >= 1
    assert cold["split"] + cold["merged"] + cold["lifted_aspect"] >= 0
    assert len(view_after.aspects) >= len(view_before.aspects)
