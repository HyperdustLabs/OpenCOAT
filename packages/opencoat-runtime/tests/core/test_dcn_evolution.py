"""Tests for :class:`~opencoat_runtime_core.dcn.evolution.DCNEvolver`."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.dcn.evolution import DCNEvolver
from opencoat_runtime_protocol import (
    ActivationState,
    Advice,
    AdviceType,
    Concern,
    ConcernRelationType,
    LifecycleState,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import ConcernRelation, PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

_NOW = datetime(2026, 5, 19, 14, 0, tzinfo=UTC)


def _concern(
    cid: str,
    *,
    keywords: list[str],
    score: float = 0.6,
    decay: float = 0.0,
    lifecycle: str = LifecycleState.ACTIVE.value,
) -> Concern:
    return Concern(
        id=cid,
        name=cid,
        description=cid,
        lifecycle_state=lifecycle,
        activation_state=ActivationState(score=score, decay=decay, active=True),
        pointcut=Pointcut(
            joinpoints=["before_response"],
            match=PointcutMatch(any_keywords=keywords),
        ),
        advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="x"),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.OUTPUT_LEVEL,
            target="response.body",
            priority=0.5,
        ),
    )


class TestDCNEvolver:
    def test_heuristic_merge_archives_loser(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(_concern("dup-a", keywords=["NVDA", "周三", "收盘"], score=0.8))
        store.upsert(_concern("dup-b", keywords=["NVDA", "周三", "分析"], score=0.3))
        evolver = DCNEvolver(
            concern_store=store,
            dcn_store=dcn,
            lifecycle=ConcernLifecycleManager(concern_store=store, dcn_store=dcn),
            merge_min_keyword_overlap=2,
        )
        result = evolver.run(_NOW)
        assert result.merged == 1
        assert store.get("dup-b") is not None
        assert store.get("dup-b").lifecycle_state == LifecycleState.ARCHIVED.value
        assert "dup-b" not in dcn

    def test_archive_cold_weakened(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern(
                "cold",
                keywords=["x"],
                score=0.1,
                decay=0.9,
                lifecycle=LifecycleState.WEAKENED.value,
            )
        )
        evolver = DCNEvolver(
            concern_store=store,
            dcn_store=dcn,
            lifecycle=ConcernLifecycleManager(concern_store=store, dcn_store=dcn),
        )
        result = evolver.run(_NOW)
        assert result.archived == 1
        assert store.get("cold").lifecycle_state == LifecycleState.ARCHIVED.value

    def test_declared_duplicates_relation_triggers_merge(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        left = _concern("left", keywords=["a", "b", "c"], score=0.5)
        right = _concern("right", keywords=["d"], score=0.9)
        left = left.model_copy(
            update={
                "relations": [
                    ConcernRelation(
                        target_concern_id="right",
                        relation_type=ConcernRelationType.SPECIALIZES,
                        layer="semantic",
                    )
                ]
            }
        )
        store.upsert(left)
        store.upsert(right)
        evolver = DCNEvolver(
            concern_store=store,
            dcn_store=dcn,
            lifecycle=ConcernLifecycleManager(concern_store=store, dcn_store=dcn),
        )
        result = evolver.run(_NOW)
        assert result.merged == 1
        assert store.get("right").lifecycle_state == LifecycleState.ARCHIVED.value

    def test_heuristic_merge_three_way_cluster(self) -> None:
        """Stale combination pairs must not merge into an already-archived loser."""
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        kw = ["NVDA", "周三", "收盘", "分析"]
        store.upsert(_concern("cluster-a", keywords=kw, score=0.5))
        store.upsert(_concern("cluster-b", keywords=kw, score=0.6))
        store.upsert(_concern("cluster-c", keywords=kw, score=0.4))
        evolver = DCNEvolver(
            concern_store=store,
            dcn_store=dcn,
            lifecycle=ConcernLifecycleManager(concern_store=store, dcn_store=dcn),
            merge_min_keyword_overlap=3,
        )
        result = evolver.run(_NOW)
        assert result.merged == 2
        winner = store.get("cluster-b")
        assert winner is not None
        assert winner.lifecycle_state in {
            LifecycleState.ACTIVE.value,
            LifecycleState.REINFORCED.value,
        }
        for loser_id in ("cluster-a", "cluster-c"):
            loser = store.get(loser_id)
            assert loser is not None
            assert loser.lifecycle_state == LifecycleState.ARCHIVED.value
            assert loser_id not in dcn
