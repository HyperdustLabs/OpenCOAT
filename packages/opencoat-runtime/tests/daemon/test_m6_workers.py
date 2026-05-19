"""M6 heartbeat workers — decay and conflict scanner."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.meta.lifecycle_control import DefaultLifecycleControl
from opencoat_runtime_daemon.runtime_builder import build_heartbeat_maintenance
from opencoat_runtime_daemon.workers import ConflictScannerWorker, DecayWorker
from opencoat_runtime_protocol import (
    ActivationState,
    Advice,
    AdviceType,
    Concern,
    ConcernRelationType,
    LifecycleState,
    Pointcut,
    WeavingPolicy,
    WeavingLevel,
    WeavingOperation,
)
from opencoat_runtime_protocol.envelopes import ConcernRelation, PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

_NOW = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


def _concern(
    cid: str,
    *,
    keywords: list[str],
    joinpoints: list[str] | None = None,
    decay: float = 0.0,
    lifecycle: str = LifecycleState.ACTIVE.value,
) -> Concern:
    return Concern(
        id=cid,
        name=cid,
        description=cid,
        lifecycle_state=lifecycle,
        activation_state=ActivationState(score=0.6, decay=decay, active=True),
        pointcut=Pointcut(
            joinpoints=joinpoints or ["before_response"],
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


class TestDecayWorker:
    def test_bumps_decay_and_archives_at_threshold(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern("cold", keywords=["a"], decay=0.96, joinpoints=["before_response"])
        )
        policy = DefaultLifecycleControl(decay_step=0.1, archive_threshold=1.0)
        worker = DecayWorker(
            concern_store=store,
            dcn_store=dcn,
            policy=policy,
            lifecycle=ConcernLifecycleManager(concern_store=store, dcn_store=dcn),
        )
        stats = worker.run(_NOW)
        assert stats["archived"] == 1
        archived = store.get("cold")
        assert archived is not None
        assert archived.lifecycle_state == LifecycleState.ARCHIVED.value

    def test_skips_archived_concerns(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern(
                "gone",
                keywords=["x"],
                lifecycle=LifecycleState.ARCHIVED.value,
                decay=0.9,
            )
        )
        worker = DecayWorker(concern_store=store, dcn_store=dcn)
        stats = worker.run(_NOW)
        assert stats["touched"] == 0


class TestConflictScannerWorker:
    def test_links_overlapping_active_concerns(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(_concern("a", keywords=["NVDA", "周三", "收盘"]))
        store.upsert(_concern("b", keywords=["NVDA", "周三", "分析"]))
        worker = ConflictScannerWorker(concern_store=store, dcn_store=dcn, min_keyword_overlap=2)
        stats = worker.run(_NOW)
        assert stats["edges_added"] >= 2
        a = store.get("a")
        b = store.get("b")
        assert a is not None and b is not None
        assert any(
            r.target_concern_id == "b" and r.relation_type == ConcernRelationType.CONFLICTS_WITH
            for r in a.relations
        )
        assert dcn.neighbors("a", relation_type=ConcernRelationType.CONFLICTS_WITH) == ["b"]

    def test_syncs_declared_relations_to_dcn(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        left = _concern("left", keywords=["x"])
        right = _concern("right", keywords=["y"])
        left = left.model_copy(
            update={
                "relations": [
                    ConcernRelation(
                        target_concern_id="right",
                        relation_type=ConcernRelationType.CONFLICTS_WITH,
                        layer="runtime",
                    )
                ]
            }
        )
        store.upsert(left)
        store.upsert(right)
        worker = ConflictScannerWorker(concern_store=store, dcn_store=dcn)
        stats = worker.run(_NOW)
        assert stats["edges_added"] >= 1
        assert "right" in dcn.neighbors("left", relation_type=ConcernRelationType.CONFLICTS_WITH)


class TestHeartbeatMaintenance:
    def test_runtime_tick_reports_maintenance_counts(self) -> None:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(_concern("a", keywords=["NVDA", "周三", "收盘"]))
        store.upsert(_concern("b", keywords=["NVDA", "周三", "分析"]))
        rt = OpenCOATRuntime(
            concern_store=store,
            dcn_store=dcn,
            llm=StubLLMClient(),
            heartbeat_maintenance=build_heartbeat_maintenance(store, dcn),
        )
        report = rt.tick(_NOW)
        assert report.candidate_count == 2
        assert report.conflict_count >= 1
