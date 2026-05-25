"""Tests for PlasticityEngine reweight attribution."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_protocol import Concern
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _record(kind: str, **reflex: object) -> RtRecord:
    return RtRecord(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        session_id="s1",
        turn_id="run-1",
        joinpoint="before_tool_call",
        hook="before_tool_call",
        signal=RtSignal(kind=kind, reflex=dict(reflex) if reflex else None),
        r=0.0,
    )


def test_tool_blocked_reinforces_reflex_concern() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(Concern(id="demo-tool-block", name="block"))
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    engine = PlasticityEngine(step_delta=0.1)

    stats = engine.reweight(
        [
            _record(
                "tool_blocked",
                policy_id="demo-tool-block",
                decision="deny",
            )
        ],
        concern_store=store,
        lifecycle=lifecycle,
    )

    assert stats.reinforced == 1
    updated = store.get("demo-tool-block")
    assert updated is not None
    assert updated.lifecycle_state == "reinforced"


def test_tool_blocked_revives_archived_concern() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    concern = Concern(id="demo-tool-block", name="block", lifecycle_state="archived")
    store.upsert(concern)
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    engine = PlasticityEngine(step_delta=0.1)

    stats = engine.reweight(
        [
            _record(
                "tool_blocked",
                policy_id="demo-tool-block",
                decision="deny",
            )
        ],
        concern_store=store,
        lifecycle=lifecycle,
    )

    assert stats.reinforced == 1
    updated = store.get("demo-tool-block")
    assert updated is not None
    assert updated.lifecycle_state == "reinforced"


def test_tool_outcome_success_reinforces_policy() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(Concern(id="demo-tool-block", name="block"))
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    engine = PlasticityEngine(step_delta=0.1)

    record = RtRecord(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        session_id="s1",
        turn_id="run-1",
        joinpoint="after_tool_call",
        hook="after_tool_call",
        signal=RtSignal(
            kind="tool_outcome",
            tool_name="read",
            reflex={"policy_id": "demo-tool-block", "decision": "rewrite"},
        ),
        r=1.0,
    )
    stats = engine.reweight([record], concern_store=store, lifecycle=lifecycle)

    assert stats.reinforced == 1
    updated = store.get("demo-tool-block")
    assert updated is not None
    assert updated.activation_state is not None
    assert updated.activation_state.score > 0.0


def test_tool_outcome_error_weakens_policy() -> None:
    from opencoat_runtime_protocol import ActivationState

    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(
        Concern(
            id="demo-tool-block",
            name="block",
            activation_state=ActivationState(score=0.5, active=True, decay=0.0),
            lifecycle_state="active",
        )
    )
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    engine = PlasticityEngine(step_delta=0.1)

    record = RtRecord(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        session_id="s1",
        turn_id="run-1",
        joinpoint="after_tool_call",
        hook="after_tool_call",
        signal=RtSignal(
            kind="tool_outcome",
            tool_name="shell.exec",
            error="exit 1",
            reflex={"policy_id": "demo-tool-block", "decision": "rewrite"},
        ),
        r=0.0,
    )
    stats = engine.reweight([record], concern_store=store, lifecycle=lifecycle)

    assert stats.weakened == 1
    updated = store.get("demo-tool-block")
    assert updated is not None
    assert updated.activation_state is not None
    assert updated.activation_state.score < 0.5


def test_turn_complete_reinforces_plastic_cortex_from_advantage() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(Concern(id="cortex-h0", name="cortex", reflex=False))
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    engine = PlasticityEngine(step_delta=0.05)

    record = RtRecord(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        session_id="phase-ii",
        turn_id="t1",
        joinpoint="before_response",
        hook="before_response",
        signal=RtSignal(
            kind="turn_complete",
            payload={
                "active_aspects": [
                    {
                        "concern_id": "cortex-h0",
                        "activation_score": 1.0,
                        "plastic": True,
                    }
                ]
            },
        ),
        r=1.0,
        baseline_b=0.0,
    )
    stats = engine.reweight([record], concern_store=store, lifecycle=lifecycle)

    assert stats.reinforced == 1
    updated = store.get("cortex-h0")
    assert updated is not None
    assert updated.lifecycle_state == "reinforced"
    assert updated.activation_state is not None
    assert updated.activation_state.score == 0.55


def test_turn_complete_uses_stored_advantage_payload() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(Concern(id="cortex-h0", name="cortex", reflex=False))
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    engine = PlasticityEngine(step_delta=0.05)

    record = RtRecord(
        ts=datetime(2026, 5, 24, tzinfo=UTC),
        session_id="phase-ii-e0:ct-json",
        turn_id="t2",
        joinpoint="before_response",
        hook="before_response",
        signal=RtSignal(
            kind="turn_complete",
            payload={
                "advantage": 0.42,
                "active_aspects": [
                    {"concern_id": "cortex-h0", "activation_score": 1.0, "plastic": True}
                ],
            },
        ),
        r=1.0,
        baseline_b=0.58,
    )
    stats = engine.reweight([record], concern_store=store, lifecycle=lifecycle)

    assert stats.reinforced == 1
    updated = store.get("cortex-h0")
    assert updated is not None
    assert updated.activation_state is not None
    assert updated.activation_state.score == pytest.approx(0.52, abs=0.01)
