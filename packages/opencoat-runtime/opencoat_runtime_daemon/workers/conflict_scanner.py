"""Periodic conflict scanner — populates ``conflicts_with`` edges."""

from __future__ import annotations

from datetime import datetime
from itertools import combinations

from opencoat_runtime_core.ports import ConcernStore, DCNStore
from opencoat_runtime_protocol import Concern, ConcernRelationType, LifecycleState

from ._base import Worker
from ._concern_graph import (
    activation_keywords,
    has_conflict_relation,
    joinpoint_names,
    with_conflict_relation,
)

_ACTIVE_STATES = frozenset(
    {
        LifecycleState.CREATED.value,
        LifecycleState.ACTIVE.value,
        LifecycleState.REINFORCED.value,
        LifecycleState.WEAKENED.value,
        LifecycleState.REVIVED.value,
    }
)


class ConflictScannerWorker(Worker):
    """Discover likely concern pairs and persist ``conflicts_with`` in store + DCN.

    This worker does **not** resolve conflicts at weave time — that remains
    :class:`~opencoat_runtime_core.resolver.conflict.ConflictResolver` on the hot path.
    """

    def __init__(
        self,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        min_keyword_overlap: int = 2,
        max_catalog: int = 128,
    ) -> None:
        self._concern_store = concern_store
        self._dcn_store = dcn_store
        self._min_overlap = max(1, min_keyword_overlap)
        self._max_catalog = max(2, max_catalog)

    def run(self, now: datetime) -> dict:  # noqa: ARG002
        catalog = [
            c
            for c in self._concern_store.iter_all()
            if (c.lifecycle_state or LifecycleState.CREATED.value).lower() in _ACTIVE_STATES
        ][: self._max_catalog]
        edges_added = 0
        relations_added = 0
        pairs_scanned = 0

        for concern in catalog:
            self._ensure_dcn_node(concern)

        edges_added += self._sync_declared_relations(catalog)

        for left, right in combinations(catalog, 2):
            pairs_scanned += 1
            if not joinpoint_names(left) & joinpoint_names(right):
                continue
            overlap = activation_keywords(left) & activation_keywords(right)
            if len(overlap) < self._min_overlap:
                continue
            added = self._link_conflict_pair(left, right)
            edges_added += added["edges"]
            relations_added += added["relations"]

        return {
            "pairs_scanned": pairs_scanned,
            "edges_added": edges_added,
            "relations_added": relations_added,
        }

    def _ensure_dcn_node(self, concern: Concern) -> None:
        try:
            self._dcn_store.add_node(concern)
        except Exception:
            pass

    def _sync_declared_relations(self, catalog: list[Concern]) -> int:
        index = {c.id: c for c in catalog}
        added = 0
        for concern in catalog:
            for rel in concern.relations:
                if rel.relation_type != ConcernRelationType.CONFLICTS_WITH:
                    continue
                other = index.get(rel.target_concern_id)
                if other is None:
                    continue
                self._ensure_dcn_node(other)
                if self._add_dcn_edge(concern.id, other.id):
                    added += 1
        return added

    def _link_conflict_pair(self, left: Concern, right: Concern) -> dict[str, int]:
        edges = 0
        relations = 0
        if not has_conflict_relation(left, right.id):
            updated_left = with_conflict_relation(left, right.id)
            self._concern_store.upsert(updated_left)
            relations += 1
            left = updated_left
        if not has_conflict_relation(right, left.id):
            updated_right = with_conflict_relation(right, left.id)
            self._concern_store.upsert(updated_right)
            relations += 1
            right = updated_right
        if self._add_dcn_edge(left.id, right.id):
            edges += 1
        if self._add_dcn_edge(right.id, left.id):
            edges += 1
        return {"edges": edges, "relations": relations}

    def _add_dcn_edge(self, src: str, dst: str) -> bool:
        try:
            self._dcn_store.add_edge(src, dst, ConcernRelationType.CONFLICTS_WITH)
        except KeyError:
            return False
        except Exception:
            return False
        return True


__all__ = ["ConflictScannerWorker"]
