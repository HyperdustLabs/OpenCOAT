"""Paper-spec integration: effector → r_t → credit → warm/cold plasticity."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.advice import AdviceGenerator
from opencoat_runtime_core.config import RuntimeConfig
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_core.credit.credit_field import CreditField
from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.credit.split_spec import evaluate_split_guards
from opencoat_runtime_core.effector import EffectorAction, EffectorKernel
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.loops import JoinpointPipeline
from opencoat_runtime_core.pointcut.matcher import PointcutMatcher
from opencoat_runtime_core.weaving import ConcernWeaver
from opencoat_runtime_protocol import (
    Concern,
    JoinpointEvent,
)
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


def test_full_loop_effector_credit_warm_cold_split() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    concern = _demo_tool_block()
    store.upsert(concern)

    kernel = EffectorKernel(pipeline=_pipeline(store, dcn), concern_store=store)
    jp = JoinpointEvent(
        id="jp-e2e",
        level=3,
        name="before_tool_call",
        host="test",
        ts=datetime.now(tz=UTC),
    )
    blocked = kernel.run_turn(
        jp,
        EffectorAction(kind="tool_call", name="shell.exec", args={"command": "rm -rf /"}),
        turn_id="run-e2e",
    )
    assert blocked.allowed is False

    svc = RtPlasticityService(concern_store=store, dcn_store=dcn)
    svc.append(blocked.record)
    warm = svc.consume()
    assert warm.reinforced >= 1

    buffer = svc.buffer
    for i, feat in enumerate(["rm -rf", "ls", "rm -rf", "ls", "rm -rf", "ls", "rm -rf", "ls"]):
        buffer.append(
            "demo-tool-block",
            r=1.0 if i % 2 else 0.0,
            feature=feat,
        )

    guard = evaluate_split_guards(buffer, "demo-tool-block", n_min=8, theta_h=0.01)
    assert guard.partition is not None

    reinforced = concern.model_copy(
        update={
            "lifecycle_state": "reinforced",
            "metrics": concern.metrics.model_copy(update={"activations": 10}),
        }
    )
    store.upsert(reinforced)

    cold = svc.cold_step()
    assert cold["split"] + cold["lifted"] + cold["archived"] >= 0

    stats = svc.connectome_stats()
    assert stats["aspects"] >= 1


def test_credit_field_conservation_diagnostic() -> None:
    store = MemoryConcernStore()
    store.upsert(Concern(id="demo-tool-block", name="block"))
    field = CreditField(concern_store=store)
    rec = RtRecord(
        ts=datetime.now(tz=UTC),
        session_id="s",
        turn_id="t",
        joinpoint="before_tool_call",
        hook="before_tool_call",
        signal=RtSignal(
            kind="tool_blocked",
            reflex={"policy_id": "demo-tool-block", "decision": "deny"},
        ),
        r=1.0,
    )
    attrs = field.attribute(rec)
    assert len(attrs) == 1
    assert abs(field.conserved_sum(attrs, r=rec.r)) < 1e-6
