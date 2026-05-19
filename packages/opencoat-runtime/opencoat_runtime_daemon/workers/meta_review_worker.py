"""Meta-concern review worker (runs the 8 governance capabilities)."""

from __future__ import annotations

from datetime import datetime

from opencoat_runtime_core.meta.evolution_control import DefaultEvolutionControl
from opencoat_runtime_core.ports import ConcernStore
from opencoat_runtime_protocol import ConcernKind

from ._base import Worker


class MetaReviewWorker(Worker):
    """Inventory meta concerns and signal whether a governance review tick ran."""

    def __init__(self, *, concern_store: ConcernStore) -> None:
        self._concern_store = concern_store

    def run(self, _now: datetime) -> dict:
        catalog = list(self._concern_store.iter_all())
        control = DefaultEvolutionControl(meta_concerns=catalog)
        triggered = control.trigger_review()
        capabilities = sorted(
            {
                str(cap)
                for c in catalog
                if (c.kind or ConcernKind.CONCERN.value) == ConcernKind.META_CONCERN.value
                for cap in [getattr(c, "governance_capability", None)]
                if cap is not None
            }
        )
        return {
            "meta_concern_count": control.meta_concern_count,
            "review_triggered": triggered,
            "capabilities": capabilities,
        }


__all__ = ["MetaReviewWorker"]
