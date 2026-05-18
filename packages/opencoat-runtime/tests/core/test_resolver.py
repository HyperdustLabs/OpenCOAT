"""Tests for resolver components: Dedupe, ConflictResolver, EscalationManager,
and the :class:`ConcernResolver` facade."""

from __future__ import annotations

from opencoat_runtime_core.resolver import (
    ConcernResolver,
    ConflictResolver,
    Dedupe,
    EscalationManager,
)
from opencoat_runtime_protocol import (
    AdviceType,
    Concern,
    ConcernRelationType,
)
from opencoat_runtime_protocol.envelopes import Advice, ConcernRelation, DeclarePrecedence


def _concern(
    cid: str,
    *,
    relations: list[ConcernRelation] | None = None,
    advice: Advice | None = None,
) -> Concern:
    return Concern(id=cid, name=cid, relations=relations or [], advice=advice)


def _rel(target: str, rtype: ConcernRelationType, weight: float = 1.0) -> ConcernRelation:
    return ConcernRelation(target_concern_id=target, relation_type=rtype, weight=weight)


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


class TestDedupe:
    def test_specializes_relation_drops_target(self) -> None:
        # A specializes B -> drop B (keep the more specific one)
        a = _concern("a", relations=[_rel("b", ConcernRelationType.SPECIALIZES)])
        b = _concern("b")
        kept = Dedupe().collapse([a, b])
        assert [c.id for c in kept] == ["a"]

    def test_generalizes_relation_drops_self(self) -> None:
        # A generalizes B -> A is broader; drop A, keep B.
        a = _concern("a", relations=[_rel("b", ConcernRelationType.GENERALIZES)])
        b = _concern("b")
        kept = Dedupe().collapse([a, b])
        assert [c.id for c in kept] == ["b"]

    def test_low_weight_relation_does_not_collapse(self) -> None:
        a = _concern(
            "a",
            relations=[_rel("b", ConcernRelationType.SPECIALIZES, weight=0.1)],
        )
        b = _concern("b")
        kept = Dedupe().collapse([a, b])
        assert {c.id for c in kept} == {"a", "b"}

    def test_dangling_relation_target_is_ignored(self) -> None:
        a = _concern("a", relations=[_rel("ghost", ConcernRelationType.SPECIALIZES)])
        kept = Dedupe().collapse([a])
        assert [c.id for c in kept] == ["a"]

    def test_no_concerns_returns_empty(self) -> None:
        assert Dedupe().collapse([]) == []


# ---------------------------------------------------------------------------
# ConflictResolver
# ---------------------------------------------------------------------------


class TestConflictResolver:
    def test_detects_symmetric_conflict_once(self) -> None:
        a = _concern("a", relations=[_rel("b", ConcernRelationType.CONFLICTS_WITH)])
        b = _concern("b", relations=[_rel("a", ConcernRelationType.CONFLICTS_WITH)])
        pairs = ConflictResolver().detect([a, b])
        assert len(pairs) == 1
        ids = sorted([pairs[0][0].id, pairs[0][1].id])
        assert ids == ["a", "b"]

    def test_higher_score_wins_symmetric_conflict(self) -> None:
        a = _concern("a", relations=[_rel("b", ConcernRelationType.CONFLICTS_WITH)])
        b = _concern("b")
        kept = ConflictResolver().resolve([(a, 0.9), (b, 0.4)])
        assert [c.id for c, _ in kept] == ["a"]

    def test_suppresses_relation_drops_target_regardless_of_score(self) -> None:
        # Even if the target has a higher score, ``suppresses`` is hard.
        a = _concern("a", relations=[_rel("b", ConcernRelationType.SUPPRESSES)])
        b = _concern("b")
        kept = ConflictResolver().resolve([(b, 0.9), (a, 0.1)])
        assert [c.id for c, _ in kept] == ["a"]

    def test_tie_drops_lexicographically_larger_id(self) -> None:
        a = _concern("c-a", relations=[_rel("c-b", ConcernRelationType.CONFLICTS_WITH)])
        b = _concern("c-b")
        kept = ConflictResolver().resolve([(a, 0.5), (b, 0.5)])
        assert [c.id for c, _ in kept] == ["c-a"]

    def test_declare_precedence_drops_lower_ranked_peer(self) -> None:
        high = Concern(
            id="high",
            name="high",
            declarations=[DeclarePrecedence(order=["high", "low"])],
        )
        low = _concern("low")
        kept = ConflictResolver().resolve([(low, 0.99), (high, 0.1)])
        assert [c.id for c, _ in kept] == ["high"]

    def test_declares_precedence_over_relation(self) -> None:
        winner = _concern(
            "winner",
            relations=[_rel("loser", ConcernRelationType.DECLARES_PRECEDENCE_OVER)],
        )
        loser = _concern("loser")
        kept = ConflictResolver().resolve([(loser, 0.9), (winner, 0.1)])
        assert [c.id for c, _ in kept] == ["winner"]


# ---------------------------------------------------------------------------
# EscalationManager
# ---------------------------------------------------------------------------


class TestEscalationManager:
    def test_only_escalation_notice_advice_triggers(self) -> None:
        mgr = EscalationManager()
        normal = Advice(type=AdviceType.REASONING_GUIDANCE, content="ok")
        escalate = Advice(type=AdviceType.ESCALATION_NOTICE, content="alert")
        concern = _concern("c")
        assert mgr.should_escalate(concern, normal) is False
        assert mgr.should_escalate(concern, escalate) is True

    def test_emit_payload_carries_concern_id_and_content(self) -> None:
        mgr = EscalationManager()
        advice = Advice(
            type=AdviceType.ESCALATION_NOTICE,
            content="oops",
            rationale="because",
        )
        payload = mgr.emit(_concern("c-1"), advice)
        assert payload["concern_id"] == "c-1"
        assert payload["content"] == "oops"
        assert payload["rationale"] == "because"
        assert payload["type"] == "escalation_notice"
        assert "ts" in payload


# ---------------------------------------------------------------------------
# ConcernResolver facade
# ---------------------------------------------------------------------------


class TestConcernResolver:
    def test_full_pipeline_dedupes_then_resolves_conflicts(self) -> None:
        # a specializes b -> drop b
        # a conflicts_with c, a wins (higher score) -> drop c
        a = _concern(
            "a",
            relations=[
                _rel("b", ConcernRelationType.SPECIALIZES),
                _rel("c", ConcernRelationType.CONFLICTS_WITH),
            ],
        )
        b = _concern("b")
        c = _concern("c")
        ranked = [(a, 0.9), (b, 0.8), (c, 0.5)]
        out = ConcernResolver().resolve(ranked)
        assert [x.id for x, _ in out] == ["a"]

    def test_escalation_side_channel_collected(self) -> None:
        escalate_advice = Advice(type=AdviceType.ESCALATION_NOTICE, content="alert")
        a = _concern("a", advice=escalate_advice)
        b = _concern("b")
        resolver = ConcernResolver()
        resolver.resolve([(a, 0.9), (b, 0.5)])
        assert len(resolver.last_escalations) == 1
        assert resolver.last_escalations[0]["concern_id"] == "a"

    def test_resolve_empty_input_returns_empty_and_clears_escalations(self) -> None:
        resolver = ConcernResolver()
        assert resolver.resolve([]) == []
        assert resolver.last_escalations == []

    def test_last_escalations_isolated_from_internal_state(self) -> None:
        resolver = ConcernResolver()
        a = _concern(
            "a",
            advice=Advice(type=AdviceType.ESCALATION_NOTICE, content="alert"),
        )
        resolver.resolve([(a, 0.9)])
        snapshot = resolver.last_escalations
        snapshot.clear()
        # internal copy survives mutation of the snapshot
        assert len(resolver.last_escalations) == 1
