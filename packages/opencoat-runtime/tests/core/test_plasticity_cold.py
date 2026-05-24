"""Tests for PlasticityEngine cold_step lift/archive."""

from __future__ import annotations

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_protocol import ActivationState, Concern
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def test_cold_step_lifts_reinforced_high_score() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(
        Concern(
            id="strong-guard",
            name="guard",
            lifecycle_state="reinforced",
            activation_state=ActivationState(score=0.8, active=True, decay=0.0),
        )
    )
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    stats = PlasticityEngine().cold_step(concern_store=store, dcn_store=dcn, lifecycle=lifecycle)

    assert stats.lifted == 1
    updated = store.get("strong-guard")
    assert updated is not None
    assert updated.reflex is True


def test_cold_step_archives_weak_low_score() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(
        Concern(
            id="weak-hint",
            name="hint",
            lifecycle_state="weakened",
            activation_state=ActivationState(score=0.05, active=False, decay=0.0),
        )
    )
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    stats = PlasticityEngine().cold_step(concern_store=store, dcn_store=dcn, lifecycle=lifecycle)

    assert stats.archived == 1
    updated = store.get("weak-hint")
    assert updated is not None
    assert updated.lifecycle_state == "archived"
