"""Synapse-level plasticity — edge reweight / strengthen (architecture ii)."""

from __future__ import annotations

from opencoat_runtime_protocol import ConcernRelationType

from opencoat_runtime_core.connectome.model import build_connectome_view
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.ports import ConcernStore, DCNStore

_ACTIVATES = ConcernRelationType.ACTIVATES


def _edge_weight(
    dcn_store: DCNStore,
    src: str,
    dst: str,
    relation: ConcernRelationType,
) -> float | None:
    getter = getattr(dcn_store, "edge_weight", None)
    if getter is None:
        return None
    return getter(src, dst, relation)


def strengthen_edge(
    dcn_store: DCNStore,
    src: str,
    dst: str,
    *,
    relation: ConcernRelationType = _ACTIVATES,
    delta: float = 0.08,
    floor: float = 0.2,
) -> bool:
    """Raise edge weight (LTP) or create a new synapse at ``floor + delta``."""
    if not 0.0 < delta <= 1.0:
        return False
    current = _edge_weight(dcn_store, src, dst, relation)
    next_w = min(1.0, (current if current is not None else floor) + delta)
    try:
        dcn_store.add_edge(src, dst, relation, weight=next_w)
    except Exception:
        return False
    return True


def weaken_edge(
    dcn_store: DCNStore,
    src: str,
    dst: str,
    *,
    relation: ConcernRelationType = _ACTIVATES,
    delta: float = 0.06,
) -> bool:
    current = _edge_weight(dcn_store, src, dst, relation)
    if current is None:
        return False
    next_w = max(0.0, current - delta)
    if next_w < 0.05:
        try:
            dcn_store.remove_edge(src, dst, relation)
        except Exception:
            return False
        return True
    try:
        dcn_store.add_edge(src, dst, relation, weight=next_w)
    except Exception:
        return False
    return True


def strengthen_coactivated_pairs(
    dcn_store: DCNStore,
    pairs: list[tuple[str, str]],
    *,
    bidirectional: bool = True,
    delta: float = 0.08,
) -> int:
    """Strengthen ACTIVATES synapses for co-firing aspect pairs."""
    touched = 0
    for a, b in pairs:
        if a == b:
            continue
        if strengthen_edge(dcn_store, a, b, delta=delta):
            touched += 1
        if bidirectional and strengthen_edge(dcn_store, b, a, delta=delta):
            touched += 1
    return touched


def reweight_synapses_from_records(
    records: list[RtRecord],
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    co_pairs: list[tuple[str, str]] | None = None,
    step_delta: float = 0.05,
) -> dict[str, int]:
    """Edge-level warm plasticity driven by ``r_t`` advantage and co-activation."""
    view = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)
    strengthened = 0
    weakened = 0
    skipped = 0

    for record in records:
        reflex = record.signal.reflex if isinstance(record.signal.reflex, dict) else {}
        policy_id = reflex.get("policy_id")
        if not isinstance(policy_id, str) or not policy_id.strip():
            skipped += 1
            continue
        cid = policy_id.strip()
        if view.is_conserved(cid) or cid not in view.aspects:
            skipped += 1
            continue
        advantage = record.r - record.baseline_b
        if advantage > 0.05:
            for neighbor in dcn_store.neighbors(cid, relation_type=_ACTIVATES):
                if view.is_conserved(neighbor):
                    continue
                if strengthen_edge(dcn_store, neighbor, cid, delta=step_delta):
                    strengthened += 1
        elif advantage < -0.05:
            for neighbor in dcn_store.neighbors(cid, relation_type=_ACTIVATES):
                if weaken_edge(dcn_store, neighbor, cid, delta=step_delta):
                    weakened += 1

    strengthened += strengthen_coactivated_pairs(
        dcn_store,
        co_pairs or [],
        delta=step_delta,
    )

    return {
        "synapses_strengthened": strengthened,
        "synapses_weakened": weakened,
        "synapses_skipped": skipped,
    }


__all__ = [
    "reweight_synapses_from_records",
    "strengthen_coactivated_pairs",
    "strengthen_edge",
    "weaken_edge",
]
