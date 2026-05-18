"""Concern Resolver — v0.1 §20.8.

The resolver is the second stage of the coordinator pipeline (after the
priority ranker, before budget enforcement). Its sole job is to *prune*
the ranked list:

1. **Dedupe** — collapse near-duplicates via ``generalizes`` /
   ``specializes`` relations.
2. **Conflict resolve** — drop losers of ``conflicts_with`` and
   ``suppresses`` relations.
3. **Escalation tagging** — surface concerns whose advice is an
   ``escalation_notice`` so the daemon can fan them out as host alerts
   (without removing them from the vector).

Step 3 produces a side payload (``last_escalations``) rather than mutating
the ranked list, so the rest of the pipeline does not need to be aware of
escalations. The coordinator reads it after :meth:`resolve` returns.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opencoat_runtime_protocol import Concern

from .conflict import ConflictResolver
from .dedupe import Dedupe
from .escalation import EscalationManager


class ConcernResolver:
    def __init__(
        self,
        *,
        conflict: ConflictResolver | None = None,
        dedupe: Dedupe | None = None,
        escalation: EscalationManager | None = None,
    ) -> None:
        self._conflict = conflict or ConflictResolver()
        self._dedupe = dedupe or Dedupe()
        self._escalation = escalation or EscalationManager()
        self._last_escalations: list[dict[str, Any]] = []

    def resolve(
        self,
        ranked: list[tuple[Concern, float]],
        *,
        concern_catalog: Sequence[Concern] | None = None,
    ) -> list[tuple[Concern, float]]:
        if not ranked:
            self._last_escalations = []
            return []

        # 1. dedupe — operate on the concern list, then rejoin scores.
        score_map = {c.id: s for c, s in ranked}
        deduped_concerns = self._dedupe.collapse([c for c, _ in ranked])
        deduped_ids = {c.id for c in deduped_concerns}
        dedup_ranked = [(c, score_map[c.id]) for c, _ in ranked if c.id in deduped_ids]

        # 2. conflict resolution
        resolved = self._conflict.resolve(dedup_ranked, concern_catalog=concern_catalog)

        # 3. escalation tagging (read-only side channel)
        self._last_escalations = self._collect_escalations(resolved)

        return resolved

    @property
    def last_escalations(self) -> list[dict[str, Any]]:
        """Escalation payloads produced by the most recent :meth:`resolve` call."""
        return list(self._last_escalations)

    def _collect_escalations(
        self,
        resolved: list[tuple[Concern, float]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for concern, _ in resolved:
            if self._escalation.should_escalate(concern, concern.advice):
                out.append(self._escalation.emit(concern, concern.advice))
        return out


__all__ = ["ConcernResolver"]
