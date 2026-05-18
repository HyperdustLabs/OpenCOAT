"""Tests for :class:`ConcernVectorBuilder`."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.concern.vector import ConcernVectorBuilder
from opencoat_runtime_core.config import RuntimeBudgets
from opencoat_runtime_protocol.envelopes import ActiveConcern


def _builder(**budgets: int) -> ConcernVectorBuilder:
    return ConcernVectorBuilder(budgets=RuntimeBudgets(**budgets))


def test_empty_vector_has_no_active_concerns_and_carries_budget() -> None:
    builder = _builder()
    vec = builder.empty(weave_id="turn-1")
    assert vec.weave_id == "turn-1"
    assert vec.active_concerns == []
    assert vec.budget is not None
    assert vec.budget.max_active_concerns == 12  # default
    assert vec.budget.max_injection_tokens == 800


def test_build_preserves_active_concerns_and_assigns_ts_when_missing() -> None:
    builder = _builder(max_active_concerns=4, max_injection_tokens=200)
    active = [ActiveConcern(concern_id="c-1", activation_score=0.7)]

    vec = builder.build(weave_id="turn-2", agent_session_id="sess-1", active=active)

    assert vec.weave_id == "turn-2"
    assert vec.agent_session_id == "sess-1"
    assert vec.active_concerns == active
    assert vec.budget.max_active_concerns == 4
    assert vec.budget.max_injection_tokens == 200
    assert vec.ts is not None  # auto-stamped
    assert vec.ts.tzinfo is not None  # tz-aware


def test_build_uses_explicit_timestamp_when_supplied() -> None:
    builder = _builder()
    fixed = datetime(2026, 5, 7, 12, 0, tzinfo=UTC)
    vec = builder.build(weave_id="turn-3", active=[], ts=fixed)
    assert vec.ts == fixed


def test_build_copies_active_list_so_caller_mutation_does_not_leak() -> None:
    builder = _builder()
    active = [ActiveConcern(concern_id="c-1", activation_score=0.5)]
    vec = builder.build(weave_id="turn-4", active=active)
    active.append(ActiveConcern(concern_id="c-2", activation_score=0.9))
    assert len(vec.active_concerns) == 1
    assert vec.active_concerns[0].concern_id == "c-1"
