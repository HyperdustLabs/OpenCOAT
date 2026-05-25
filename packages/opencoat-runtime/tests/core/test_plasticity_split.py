"""Cold-path connectome split via PlasticityEngine."""

from __future__ import annotations

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_protocol import ActivationState, Concern, ConcernMetrics, PointcutDef
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def test_cold_step_splits_reinforced_multi_keyword_concern() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(
        Concern(
            id="wide-policy",
            name="wide",
            lifecycle_state="reinforced",
            activation_state=ActivationState(score=0.7, active=True, decay=0.0),
            metrics=ConcernMetrics(activations=5),
            pointcuts=[
                PointcutDef(
                    id="pc",
                    joinpoints=["before_tool_call"],
                    match=PointcutMatch(
                        any_keywords=["alpha", "beta", "gamma", "delta"],
                    ),
                ),
            ],
        )
    )
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    stats = PlasticityEngine().cold_step(concern_store=store, dcn_store=dcn, lifecycle=lifecycle)

    assert stats.split == 1
    assert store.get("wide-policy--a") is not None
    assert store.get("wide-policy--b") is not None
    parent = store.get("wide-policy")
    assert parent is not None
    assert parent.lifecycle_state == "archived"


def test_delta_f_split_without_pointcut_keywords() -> None:
    from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer

    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    parent = Concern(
        id="h0-cortex",
        name="cortex",
        lifecycle_state="reinforced",
        activation_state=ActivationState(score=0.7, active=True, decay=0.0),
        metrics=ConcernMetrics(activations=4),
        pointcuts=[],
    )
    store.upsert(parent)
    dcn.add_node(parent)
    buffer = ConcernRtBuffer()
    for i in range(8):
        feature = "fail-task" if i % 2 == 0 else "ok-task"
        buffer.append("h0-cortex", r=0.0 if i % 2 == 0 else 1.0, feature=feature)

    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    stats = PlasticityEngine(split_beta=0.01).cold_step(
        concern_store=store, dcn_store=dcn, lifecycle=lifecycle, buffer=buffer
    )

    assert stats.split == 1
    assert store.get("h0-cortex--a") is not None
    assert store.get("h0-cortex--b") is not None
