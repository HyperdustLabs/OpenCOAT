"""Multi-neuron connectome routing (architecture ii §3.4, §7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opencoat_runtime_protocol import Concern, ConcernRelationType, JoinpointEvent

from opencoat_runtime_core.connectome.model import ConnectomeView, build_connectome_view
from opencoat_runtime_core.coordinator._util import clamp01
from opencoat_runtime_core.credit.eligibility import EligibilityField
from opencoat_runtime_core.ports import ConcernStore, DCNStore

_ACTIVATES = ConcernRelationType.ACTIVATES
_DEPENDS = ConcernRelationType.DEPENDS_ON


@dataclass(frozen=True)
class RoutedCandidate:
    concern: Concern
    pointcut_score: float
    route_score: float
    bucket: str
    via_hub: str | None = None


@dataclass(frozen=True)
class ConnectomeRoutingConfig:
    """Tunable routing / MoE knobs."""

    enabled: bool = True
    synapse_gain: float = 0.35
    hub_boost: float = 0.25
    moe_per_bucket: int = 6
    min_route_score: float = 0.02


def joinpoint_bucket(joinpoint_name: str) -> str:
    """MoE bucket key from joinpoint (e.g. ``tool``, ``queue``, ``memory``)."""
    name = (joinpoint_name or "").strip()
    if not name:
        return "default"
    if "." in name:
        return name.split(".", 1)[0]
    if "_" in name:
        return name.split("_", 1)[0]
    return name


class ConnectomeRouter:
    """Route matched aspects through synapse-weighted graph + MoE buckets."""

    def __init__(self, config: ConnectomeRoutingConfig | None = None) -> None:
        self._cfg = config or ConnectomeRoutingConfig()

    def route(
        self,
        joinpoint: JoinpointEvent,
        pointcut_hits: list[tuple[Concern, float]],
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        view: ConnectomeView | None = None,
        eligibility: EligibilityField | None = None,
    ) -> list[tuple[Concern, float]]:
        """Return ``(concern, route_score)`` for the coordinator (architecture ii)."""
        if not pointcut_hits:
            return []
        if not self._cfg.enabled:
            return [(c, clamp01(s)) for c, s in pointcut_hits]

        snap = view or build_connectome_view(
            concern_store=concern_store,
            dcn_store=dcn_store,
        )
        base_scores = {c.id: clamp01(s) for c, s in pointcut_hits}
        concern_by_id = {c.id: c for c, _ in pointcut_hits}

        incoming = _incoming_activates(snap)
        hub_members = _lift_hub_members(snap, dcn_store)

        routed: list[RoutedCandidate] = []
        jp_bucket = joinpoint_bucket(joinpoint.name)

        for concern, pc_score in pointcut_hits:
            score = base_scores[concern.id]
            score += _synapse_boost(
                concern.id,
                base_scores,
                incoming,
                gain=self._cfg.synapse_gain,
            )
            if eligibility is not None:
                e_a = eligibility.aspect_e(concern.id)
                score *= 0.25 + 0.75 * min(1.0, e_a)
            bucket = _neuron_bucket(concern, jp_bucket)
            routed.append(
                RoutedCandidate(
                    concern=concern,
                    pointcut_score=pc_score,
                    route_score=clamp01(score),
                    bucket=bucket,
                )
            )

        _expand_lift_hubs(
            routed,
            hub_members,
            concern_by_id,
            concern_store=concern_store,
            base_scores=base_scores,
            incoming=incoming,
            jp_bucket=jp_bucket,
            hub_boost=self._cfg.hub_boost,
            synapse_gain=self._cfg.synapse_gain,
        )

        selected = _moe_select(
            routed,
            reflex_core=snap.reflex_core,
            per_bucket=self._cfg.moe_per_bucket,
            min_score=self._cfg.min_route_score,
        )
        return [(r.concern, r.route_score) for r in selected]

    def route_debug(
        self,
        joinpoint: JoinpointEvent,
        pointcut_hits: list[tuple[Concern, float]],
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
    ) -> list[dict[str, Any]]:
        """Structured routing trace for JSON-RPC / tests."""
        snap = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)
        selected_ids = {
            c.id
            for c, _ in self.route(
                joinpoint,
                pointcut_hits,
                concern_store=concern_store,
                dcn_store=dcn_store,
                view=snap,
            )
        }
        out: list[dict[str, Any]] = []
        for concern, pc in pointcut_hits:
            out.append(
                {
                    "concern_id": concern.id,
                    "neuron_type": concern.neuron_type,
                    "pointcut_score": pc,
                    "selected": concern.id in selected_ids,
                    "bucket": _neuron_bucket(concern, joinpoint_bucket(joinpoint.name)),
                }
            )
        return out


def _neuron_bucket(concern: Concern, jp_bucket: str) -> str:
    if concern.reflex or concern.neuron_type == "inhibitory":
        return "reflex"
    return jp_bucket


def _incoming_activates(view: ConnectomeView) -> dict[str, list[tuple[str, float]]]:
    incoming: dict[str, list[tuple[str, float]]] = {}
    for edge in view.edges:
        if edge.relation != _ACTIVATES:
            continue
        incoming.setdefault(edge.dst, []).append((edge.src, edge.weight))
    return incoming


def _synapse_boost(
    concern_id: str,
    base_scores: dict[str, float],
    incoming: dict[str, list[tuple[str, float]]],
    *,
    gain: float,
) -> float:
    boost = 0.0
    for src, weight in incoming.get(concern_id, []):
        parent_a = base_scores.get(src, 0.25)
        boost += gain * weight * parent_a
    return boost


def _lift_hub_members(
    view: ConnectomeView,
    dcn_store: DCNStore,
) -> dict[str, list[str]]:
    hubs: dict[str, list[str]] = {}
    for cid, concern in view.aspects.items():
        if cid.startswith("lift.") or concern.name.startswith("lift("):
            members: list[str] = []
            for rel in (_DEPENDS, _ACTIVATES):
                members.extend(dcn_store.neighbors(cid, relation_type=rel))
            if members:
                hubs[cid] = sorted(set(members))
    return hubs


def _expand_lift_hubs(
    routed: list[RoutedCandidate],
    hub_members: dict[str, list[str]],
    concern_by_id: dict[str, Concern],
    *,
    concern_store: ConcernStore,
    base_scores: dict[str, float],
    incoming: dict[str, list[tuple[str, float]]],
    jp_bucket: str,
    hub_boost: float,
    synapse_gain: float,
) -> None:
    """Pull member aspects forward when a lift hub is active (aspect-of-aspect)."""
    present = {r.concern.id for r in routed}
    hub_scores = {r.concern.id: r.route_score for r in routed if r.concern.id in hub_members}

    for hub_id, members in hub_members.items():
        hub_score = hub_scores.get(hub_id)
        if hub_score is None:
            continue
        for mid in members:
            if mid in present:
                continue
            concern = concern_by_id.get(mid) or concern_store.get(mid)
            if concern is None or concern.reflex:
                continue
            score = clamp01(hub_score * hub_boost + base_scores.get(mid, 0.0))
            score += _synapse_boost(mid, base_scores, incoming, gain=synapse_gain)
            routed.append(
                RoutedCandidate(
                    concern=concern,
                    pointcut_score=base_scores.get(mid, 0.0),
                    route_score=score,
                    bucket=_neuron_bucket(concern, jp_bucket),
                    via_hub=hub_id,
                )
            )
            present.add(mid)


def _moe_select(
    routed: list[RoutedCandidate],
    *,
    reflex_core: frozenset[str],
    per_bucket: int,
    min_score: float,
) -> list[RoutedCandidate]:
    """Per-bucket top-k (MoE) plus all reflex matches."""
    reflex: list[RoutedCandidate] = []
    buckets: dict[str, list[RoutedCandidate]] = {}
    for r in routed:
        if r.concern.id in reflex_core or r.bucket == "reflex":
            reflex.append(r)
            continue
        buckets.setdefault(r.bucket, []).append(r)

    out: list[RoutedCandidate] = list(reflex)
    seen: set[str] = {r.concern.id for r in out}
    for _bucket, items in sorted(buckets.items()):
        items.sort(key=lambda x: x.route_score, reverse=True)
        selected_from_bucket = False
        for r in items[: max(1, per_bucket)]:
            if r.route_score < min_score:
                continue
            if r.concern.id in seen:
                continue
            seen.add(r.concern.id)
            out.append(r)
            selected_from_bucket = True
        if not selected_from_bucket and items and not out:
            r = items[0]
            seen.add(r.concern.id)
            out.append(r)
    out.sort(key=lambda x: x.route_score, reverse=True)
    return out


__all__ = [
    "ConnectomeRouter",
    "ConnectomeRoutingConfig",
    "RoutedCandidate",
    "joinpoint_bucket",
]
