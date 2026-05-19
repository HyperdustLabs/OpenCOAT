"""MergeArchiverWorker integration."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_daemon.workers import MergeArchiverWorker
from opencoat_runtime_protocol import ActivationState, LifecycleState
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

from .test_m6_workers import _concern

_NOW = datetime(2026, 5, 19, 14, 0, tzinfo=UTC)


def test_merge_archiver_reports_counts() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    cold = _concern("cold", keywords=["x"], lifecycle=LifecycleState.WEAKENED.value)
    cold = cold.model_copy(
        update={"activation_state": ActivationState(score=0.1, decay=0.9, active=True)}
    )
    store.upsert(cold)
    worker = MergeArchiverWorker(concern_store=store, dcn_store=dcn)
    stats = worker.run(_NOW)
    assert stats["archived"] == 1
    assert stats["merged"] == 0
