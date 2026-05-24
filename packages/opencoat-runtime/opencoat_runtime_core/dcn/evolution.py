"""DCN evolver — long-term graph maintenance run on heartbeat."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations

from opencoat_runtime_protocol import Concern, ConcernRelationType, LifecycleState

from ..concern.lifecycle import ConcernLifecycleManager, InvalidLifecycleTransition
from ..ports import ConcernStore, DCNStore
from ..resolver.dedupe import Dedupe
from .concern_catalog import activation_keywords, joinpoint_names

_ACTIVE_STATES = frozenset(
    {
        LifecycleState.CREATED.value,
        LifecycleState.ACTIVE.value,
        LifecycleState.REINFORCED.value,
        LifecycleState.WEAKENED.value,
        LifecycleState.REVIVED.value,
    }
)

_MERGE_RELATIONS = frozenset(
    {
        ConcernRelationType.DUPLICATES,
        ConcernRelationType.GENERALIZES,
        ConcernRelationType.SPECIALIZES,
    }
)


@dataclass(frozen=True)
class EvolutionResult:
    merged: int = 0
    archived: int = 0


class DCNEvolver:
    """Merge near-duplicate concerns and archive cold weakened rows."""

    def __init__(
        self,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        lifecycle: ConcernLifecycleManager | None = None,
        merge_min_keyword_overlap: int = 3,
        archive_cold_decay_threshold: float = 0.85,
        archive_cold_max_score: float = 0.15,
        max_catalog: int = 128,
    ) -> None:
        self._concern_store = concern_store
        self._dcn_store = dcn_store
        self._lifecycle = lifecycle or ConcernLifecycleManager(
            concern_store=concern_store,
            dcn_store=dcn_store,
        )
        self._min_overlap = max(1, merge_min_keyword_overlap)
        self._cold_decay = archive_cold_decay_threshold
        self._cold_max_score = archive_cold_max_score
        self._max_catalog = max(2, max_catalog)
        self._dedupe = Dedupe()

    def run(self, now: datetime) -> EvolutionResult:
        catalog = self._active_catalog()
        merged = self._merge_declared(catalog)
        merged += self._merge_heuristic(catalog)
        archived = self._archive_cold(catalog)
        return EvolutionResult(merged=merged, archived=archived)

    def merge(self) -> int:
        return self.run(datetime.now()).merged

    def archive(self) -> int:
        return self.run(datetime.now()).archived

    def decay(self) -> int:
        return 0

    def optimize(self) -> int:
        return 0

    def _active_catalog(self) -> list[Concern]:
        """Return active concerns eligible for ⇩_slow structural rewrites.

        Concerns with ``reflex=True`` belong to the conserved core (A_reflex /
        brainstem) and are **excluded** from merge/archive regardless of their
        lifecycle state.  This is the M-E0 invariant: A_reflex is not subject
        to stochastic graph rewriting (MAN §1, ADR-0012 Decision 4).
        """
        return [
            c
            for c in self._concern_store.iter_all()
            if (c.lifecycle_state or LifecycleState.CREATED.value).lower() in _ACTIVE_STATES
            and not c.reflex  # conserved core: exclude A_reflex from ⇩_slow
        ][: self._max_catalog]

    def _merge_declared(self, catalog: list[Concern]) -> int:
        index = {c.id: c for c in catalog}
        merged = 0
        seen_pairs: set[tuple[str, str]] = set()
        for concern in catalog:
            if concern.id not in index:
                continue
            for rel in concern.relations:
                if rel.relation_type not in _MERGE_RELATIONS:
                    continue
                other = index.get(rel.target_concern_id)
                if other is None:
                    continue
                key = tuple(sorted((concern.id, other.id)))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                loser_id = self._dedupe._pick_loser(concern, other, rel.relation_type)
                winner_id = other.id if loser_id == concern.id else concern.id
                if self._apply_merge(loser_id, winner_id):
                    merged += 1
                    catalog[:] = [c for c in catalog if c.id not in {loser_id}]
                    index.pop(loser_id, None)
        return merged

    def _merge_heuristic(self, catalog: list[Concern]) -> int:
        merged = 0
        live_ids = {c.id for c in catalog}
        for left, right in combinations(list(catalog), 2):
            if left.id not in live_ids or right.id not in live_ids:
                continue
            if not joinpoint_names(left) & joinpoint_names(right):
                continue
            if len(activation_keywords(left) & activation_keywords(right)) < self._min_overlap:
                continue
            loser_id, winner_id = self._pick_by_score(left, right)
            if self._apply_merge(loser_id, winner_id):
                merged += 1
                live_ids.discard(loser_id)
                catalog[:] = [c for c in catalog if c.id != loser_id]
        return merged

    def _archive_cold(self, catalog: list[Concern]) -> int:
        archived = 0
        for concern in catalog:
            if (concern.lifecycle_state or "").lower() != LifecycleState.WEAKENED.value:
                continue
            activation = concern.activation_state
            if activation is None:
                continue
            if activation.decay < self._cold_decay:
                continue
            score = activation.score if activation.score is not None else 0.0
            if score > self._cold_max_score:
                continue
            try:
                self._lifecycle.archive(concern, reason="heartbeat_cold")
                archived += 1
            except InvalidLifecycleTransition:
                continue
        return archived

    def _apply_merge(self, loser_id: str, winner_id: str) -> bool:
        if loser_id == winner_id:
            return False
        loser = self._concern_store.get(loser_id)
        winner = self._concern_store.get(winner_id)
        if loser is None or winner is None:
            return False
        self._ensure_dcn_node(winner)
        self._ensure_dcn_node(loser)
        try:
            self._lifecycle.transition(loser, LifecycleState.MERGED, reason="dcn_merge")
            self._lifecycle.archive(loser, reason="dcn_merge")
        except (InvalidLifecycleTransition, KeyError):
            return False
        with contextlib.suppress(Exception):
            self._dcn_store.merge(loser_id, winner_id)
        return True

    def _ensure_dcn_node(self, concern: Concern) -> None:
        with contextlib.suppress(Exception):
            self._dcn_store.add_node(concern)

    @staticmethod
    def _pick_by_score(left: Concern, right: Concern) -> tuple[str, str]:
        def score(c: Concern) -> float:
            if c.activation_state is None or c.activation_state.score is None:
                return 0.0
            return float(c.activation_state.score)

        if score(left) > score(right):
            return right.id, left.id
        if score(right) > score(left):
            return left.id, right.id
        return (left.id, right.id) if left.id > right.id else (right.id, left.id)


__all__ = ["DCNEvolver", "EvolutionResult"]
