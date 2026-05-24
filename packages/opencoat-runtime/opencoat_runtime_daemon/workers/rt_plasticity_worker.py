"""Consume ``r_t.jsonl`` and apply warm-path reweight on heartbeat."""

from __future__ import annotations

from datetime import datetime

from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService

from ._base import Worker


class RtPlasticityWorker(Worker):
    """Run :class:`PlasticityEngine` reweight over unread ``r_t`` rows."""

    def __init__(self, *, rt_service: RtPlasticityService) -> None:
        self._rt_service = rt_service

    def run(self, now: datetime) -> dict:
        del now  # stateless — cursor lives on disk
        stats = self._rt_service.consume()
        return stats.as_dict()


__all__ = ["RtPlasticityWorker"]
