"""Periodic merge / archive worker."""

from __future__ import annotations

from datetime import datetime

from opencoat_runtime_core.dcn.evolution import DCNEvolver
from opencoat_runtime_core.ports import ConcernStore, DCNStore

from ._base import Worker


class MergeArchiverWorker(Worker):
    """Run :class:`~opencoat_runtime_core.dcn.evolution.DCNEvolver` maintenance."""

    def __init__(
        self,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        evolver: DCNEvolver | None = None,
        merge_min_keyword_overlap: int = 3,
        archive_cold_decay_threshold: float = 0.85,
        archive_cold_max_score: float = 0.15,
    ) -> None:
        self._evolver = evolver or DCNEvolver(
            concern_store=concern_store,
            dcn_store=dcn_store,
            merge_min_keyword_overlap=merge_min_keyword_overlap,
            archive_cold_decay_threshold=archive_cold_decay_threshold,
            archive_cold_max_score=archive_cold_max_score,
        )

    def run(self, _now: datetime) -> dict:
        result = self._evolver.run(_now)
        return {
            "merged": result.merged,
            "archived": result.archived,
        }


__all__ = ["MergeArchiverWorker"]
