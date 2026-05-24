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
    stats = PlasticityEngine().cold_step(concern_store=store, lifecycle=lifecycle)

    assert stats.split == 1
    assert store.get("wide-policy--a") is not None
    assert store.get("wide-policy--b") is not None
    parent = store.get("wide-policy")
    assert parent is not None
    assert parent.lifecycle_state == "archived"
