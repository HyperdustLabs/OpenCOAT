"""MetaReviewWorker."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_daemon.workers import MetaReviewWorker
from opencoat_runtime_protocol import Concern, MetaConcern
from opencoat_runtime_protocol.envelopes import GovernanceCapability
from opencoat_runtime_storage.memory import MemoryConcernStore

_NOW = datetime(2026, 5, 19, 14, 0, tzinfo=UTC)


def test_meta_review_counts_meta_concerns() -> None:
    store = MemoryConcernStore()
    store.upsert(
        MetaConcern(
            id="mc-1",
            name="budget cap",
            description="meta",
            governance_capability=GovernanceCapability.BUDGET_CONTROL,
        )
    )
    store.upsert(Concern(id="c-1", name="regular", description="d"))
    stats = MetaReviewWorker(concern_store=store).run(_NOW)
    assert stats["meta_concern_count"] == 1
    assert stats["review_triggered"] is True
