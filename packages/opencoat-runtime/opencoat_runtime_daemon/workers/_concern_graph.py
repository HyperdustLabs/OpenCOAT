"""Shared helpers for heartbeat workers that walk the concern catalog."""

from __future__ import annotations

from opencoat_runtime_protocol import Concern, ConcernRelationType
from opencoat_runtime_protocol.envelopes import ConcernRelation


def joinpoint_names(concern: Concern) -> frozenset[str]:
    names: set[str] = set()
    if concern.pointcut is not None:
        for jp in concern.pointcut.joinpoints:
            if isinstance(jp, str) and jp:
                names.add(jp)
    for pc in concern.pointcuts:
        for jp in pc.joinpoints:
            if isinstance(jp, str) and jp:
                names.add(jp)
    return frozenset(names)


def activation_keywords(concern: Concern) -> frozenset[str]:
    keywords: set[str] = set()
    if concern.pointcut is not None and concern.pointcut.match is not None:
        raw = concern.pointcut.match.any_keywords
        if raw:
            keywords.update(k for k in raw if isinstance(k, str) and k)
    for pc in concern.pointcuts:
        if pc.match is None or not pc.match.any_keywords:
            continue
        keywords.update(k for k in pc.match.any_keywords if isinstance(k, str) and k)
    return frozenset(keywords)


def has_conflict_relation(concern: Concern, other_id: str) -> bool:
    for rel in concern.relations:
        if rel.target_concern_id == other_id and rel.relation_type == ConcernRelationType.CONFLICTS_WITH:
            return True
    return False


def with_conflict_relation(concern: Concern, other_id: str) -> Concern:
    if has_conflict_relation(concern, other_id):
        return concern
    rel = ConcernRelation(
        target_concern_id=other_id,
        relation_type=ConcernRelationType.CONFLICTS_WITH,
        layer="runtime",
    )
    return concern.model_copy(update={"relations": [*concern.relations, rel]})


__all__ = [
    "activation_keywords",
    "has_conflict_relation",
    "joinpoint_names",
    "with_conflict_relation",
]
