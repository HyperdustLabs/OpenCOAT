"""Connectome state — aspects as concerns, synapses as DCN edges (v0.3 §3.1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from opencoat_runtime_protocol import Concern, ConcernRelationType

from ..ports import ConcernStore, DCNStore


@dataclass(frozen=True)
class ConnectomeEdge:
    src: str
    dst: str
    relation: ConcernRelationType
    weight: float = 1.0


@dataclass
class ConnectomeView:
    """Read-only connectome snapshot for plasticity decisions."""

    aspects: dict[str, Concern] = field(default_factory=dict)
    edges: list[ConnectomeEdge] = field(default_factory=list)
    reflex_core: frozenset[str] = field(default_factory=frozenset)

    def is_conserved(self, concern_id: str) -> bool:
        return concern_id in self.reflex_core


def build_connectome_view(
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
) -> ConnectomeView:
    aspects: dict[str, Concern] = {}
    reflex_core: set[str] = set()
    for concern in concern_store.iter_all():
        aspects[concern.id] = concern
        if concern.reflex:
            reflex_core.add(concern.id)

    edges: list[ConnectomeEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for concern in aspects.values():
        for rel in (
            ConcernRelationType.ACTIVATES,
            ConcernRelationType.SUPPORTS,
            ConcernRelationType.DEPENDS_ON,
        ):
            for neighbor in dcn_store.neighbors(concern.id, relation_type=rel):
                key = (concern.id, neighbor, rel.value)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(ConnectomeEdge(src=concern.id, dst=neighbor, relation=rel, weight=1.0))
    return ConnectomeView(
        aspects=aspects,
        edges=edges,
        reflex_core=frozenset(reflex_core),
    )


__all__ = ["ConnectomeEdge", "ConnectomeView", "build_connectome_view"]
