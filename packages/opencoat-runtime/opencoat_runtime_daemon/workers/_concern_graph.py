"""Re-export catalog helpers from core (shared with :class:`DCNEvolver`)."""

from __future__ import annotations

from opencoat_runtime_core.dcn.concern_catalog import (
    activation_keywords,
    joinpoint_names,
)
from opencoat_runtime_protocol import Concern, ConcernRelationType
from opencoat_runtime_protocol.envelopes import ConcernRelation


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
