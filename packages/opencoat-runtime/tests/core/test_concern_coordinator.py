"""End-to-end tests for :class:`ConcernCoordinator` — the full pipeline:
priority -> resolver -> budget -> top-k -> ConcernVector.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.config import RuntimeBudgets
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_protocol import (
    AdviceType,
    Concern,
    ConcernRelationType,
    JoinpointEvent,
)
from opencoat_runtime_protocol.envelopes import (
    Advice,
    ConcernRelation,
    ConcernSource,
    WeavingPolicy,
)


def _jp() -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-1",
        level=4,
        name="before_response",
        host="test-host",
        agent_session_id="sess-1",
        ts=datetime(2026, 5, 7, tzinfo=UTC),
    )


def _concern(
    cid: str,
    *,
    priority: float = 0.5,
    trust: float | None = 0.5,
    relations: list[ConcernRelation] | None = None,
    advice: Advice | None = None,
) -> Concern:
    source = ConcernSource(origin="system_default", trust=trust) if trust is not None else None
    return Concern(
        id=cid,
        name=cid,
        weaving_policy=WeavingPolicy(priority=priority),
        source=source,
        relations=relations or [],
        advice=advice,
    )


class TestConcernCoordinator:
    def test_empty_candidates_returns_empty_vector(self) -> None:
        coord = ConcernCoordinator(budgets=RuntimeBudgets())
        vec = coord.coordinate(weave_id="turn-1", candidates=[], joinpoint=_jp())
        assert vec.weave_id == "turn-1"
        assert vec.active_concerns == []
        assert coord.last_escalations == []

    def test_pipeline_orders_by_composite_score(self) -> None:
        coord = ConcernCoordinator(budgets=RuntimeBudgets())
        high = _concern("c-high", priority=0.9, trust=0.9)
        low = _concern("c-low", priority=0.1, trust=0.1)
        vec = coord.coordinate(
            weave_id="t",
            candidates=[(low, 0.5), (high, 0.5)],
            joinpoint=_jp(),
        )
        assert [a.concern_id for a in vec.active_concerns] == ["c-high", "c-low"]
        assert vec.active_concerns[0].activation_score >= vec.active_concerns[1].activation_score

    def test_resolver_drops_suppressed_concern(self) -> None:
        coord = ConcernCoordinator(budgets=RuntimeBudgets())
        suppressor = _concern(
            "sup",
            relations=[
                ConcernRelation(
                    target_concern_id="vic",
                    relation_type=ConcernRelationType.SUPPRESSES,
                )
            ],
        )
        victim = _concern("vic")
        vec = coord.coordinate(
            weave_id="t",
            candidates=[(victim, 0.9), (suppressor, 0.1)],
            joinpoint=_jp(),
        )
        assert [a.concern_id for a in vec.active_concerns] == ["sup"]

    def test_budget_max_active_caps_vector_size(self) -> None:
        coord = ConcernCoordinator(budgets=RuntimeBudgets(max_active_concerns=2))
        candidates = [(_concern(f"c-{i}", priority=0.5), 1.0 - 0.05 * i) for i in range(5)]
        vec = coord.coordinate(weave_id="t", candidates=candidates, joinpoint=_jp())
        assert len(vec.active_concerns) == 2

    def test_active_concern_carries_metadata(self) -> None:
        coord = ConcernCoordinator(budgets=RuntimeBudgets())
        advice = Advice(type=AdviceType.REASONING_GUIDANCE, content="hello")
        concern = _concern("c-1", priority=0.7, advice=advice)
        vec = coord.coordinate(
            weave_id="t",
            candidates=[(concern, 0.6)],
            joinpoint=_jp(),
        )
        active = vec.active_concerns[0]
        assert active.concern_id == "c-1"
        assert active.priority == 0.7
        assert active.injection_mode == AdviceType.REASONING_GUIDANCE.value
        assert active.matched_joinpoint == "before_response"

    def test_escalation_payloads_exposed_after_coordinate(self) -> None:
        coord = ConcernCoordinator(budgets=RuntimeBudgets())
        advice = Advice(type=AdviceType.ESCALATION_NOTICE, content="alert")
        concern = _concern("c-esc", advice=advice)
        coord.coordinate(weave_id="t", candidates=[(concern, 0.9)], joinpoint=_jp())
        assert len(coord.last_escalations) == 1
        assert coord.last_escalations[0]["concern_id"] == "c-esc"

    def test_vector_carries_runtime_budget_envelope(self) -> None:
        budgets = RuntimeBudgets(max_active_concerns=4, max_injection_tokens=100)
        coord = ConcernCoordinator(budgets=budgets)
        vec = coord.coordinate(
            weave_id="t",
            candidates=[(_concern("c"), 0.5)],
            joinpoint=_jp(),
        )
        assert vec.budget is not None
        assert vec.budget.max_active_concerns == 4
        assert vec.budget.max_injection_tokens == 100

    def test_token_budget_drops_oversized_trailing_concerns(self) -> None:
        budgets = RuntimeBudgets(max_active_concerns=10, max_injection_tokens=20)
        coord = ConcernCoordinator(budgets=budgets)
        big = Advice(type=AdviceType.REASONING_GUIDANCE, content="x" * 200)
        c0 = _concern("c-0", priority=0.9, advice=big)
        c1 = _concern("c-1", priority=0.5, advice=big)
        vec = coord.coordinate(
            weave_id="t",
            candidates=[(c0, 0.9), (c1, 0.5)],
            joinpoint=_jp(),
        )
        assert [a.concern_id for a in vec.active_concerns] == ["c-0"]
