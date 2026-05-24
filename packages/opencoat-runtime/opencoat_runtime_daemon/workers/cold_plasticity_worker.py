"""Cold-path plasticity (lift/archive) on heartbeat."""

from __future__ import annotations

from datetime import datetime

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.ports import ConcernStore, DCNStore

from ._base import Worker


class ColdPlasticityWorker(Worker):
    """Run :class:`PlasticityEngine` cold_step over the concern store."""

    def __init__(
        self,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        engine: PlasticityEngine | None = None,
    ) -> None:
        self._concern_store = concern_store
        self._lifecycle = ConcernLifecycleManager(
            concern_store=concern_store,
            dcn_store=dcn_store,
        )
        self._engine = engine or PlasticityEngine()

    def run(self, now: datetime) -> dict:
        del now
        stats = self._engine.cold_step(
            concern_store=self._concern_store,
            lifecycle=self._lifecycle,
        )
        return stats.as_dict()


__all__ = ["ColdPlasticityWorker"]
