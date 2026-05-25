"""Cold-path plasticity (split/lift/merge/connect) on heartbeat."""

from __future__ import annotations

from datetime import datetime

from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService

from ._base import Worker


class ColdPlasticityWorker(Worker):
    """Run full cold :class:`PlasticityEngine` step (ΔF split + lift + merge)."""

    def __init__(
        self,
        *,
        rt_service: RtPlasticityService,
        engine: PlasticityEngine | None = None,
    ) -> None:
        self._rt_service = rt_service
        if engine is not None:
            self._rt_service.engine = engine

    def run(self, now: datetime) -> dict:
        del now
        return self._rt_service.cold_step()


__all__ = ["ColdPlasticityWorker"]
