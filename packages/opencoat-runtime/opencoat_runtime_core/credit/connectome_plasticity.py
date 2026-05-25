"""Connectome plasticity primitives: connect / prune / lift / merge (v0.3 §3.6)."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from itertools import combinations

from opencoat_runtime_protocol import Concern, ConcernRelationType, PointcutDef
from opencoat_runtime_protocol.envelopes import PointcutMatch

from opencoat_runtime_core.connectome.model import ConnectomeView, build_connectome_view
from opencoat_runtime_core.credit.connectome_split import (
    collect_pointcut_keywords,
    materialize_split,
    propose_keyword_split,
)
from opencoat_runtime_core.credit.rewrite_gate import RewriteGate
from opencoat_runtime_core.credit.rewrite_objective import (
    score_connect,
    score_lift,
    score_merge,
    score_prune,
)
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.credit.split_spec import SplitGuardResult, evaluate_split_guards
from opencoat_runtime_core.ports import ConcernStore, DCNStore


@dataclass(frozen=True)
class ConnectomeRewriteStats:
    connected: int = 0
    pruned: int = 0
    lifted: int = 0
    merged: int = 0
    split: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "connected": self.connected,
            "pruned": self.pruned,
            "lifted": self.lifted,
            "merged": self.merged,
            "split": self.split,
        }


def connect_coactivated(
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    co_pairs: list[tuple[str, str]],
    min_weight: float = 0.2,
    buffer: ConcernRtBuffer | None = None,
    gate: RewriteGate | None = None,
    beta: float = 0.01,
) -> int:
    """Add / strengthen ACTIVATES edges for co-activated concern pairs."""
    added = 0
    view = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)
    for a, b in co_pairs:
        if a == b or view.is_conserved(a) or view.is_conserved(b):
            continue
        if a not in view.aspects or b not in view.aspects:
            continue
        objective = score_connect(
            coactivation=min_weight,
            reward_mean=_pair_reward_mean(buffer, a, b),
            beta=beta,
        )
        if gate is not None and not gate.evaluate("connect", delta_f=objective.delta_f).accepted:
            continue
        from opencoat_runtime_core.connectome.synapse_evolution import strengthen_edge

        for cid in (a, b):
            c = concern_store.get(cid)
            if c is not None:
                with suppress(Exception):
                    dcn_store.add_node(c)
        if strengthen_edge(
            dcn_store,
            a,
            b,
            delta=max(min_weight, 0.08),
            floor=min_weight,
        ) or _edge_exists(dcn_store, a, b):
            added += 1
    return added


def _edge_exists(dcn_store: DCNStore, src: str, dst: str) -> bool:
    getter = getattr(dcn_store, "edge_weight", None)
    if getter is None:
        return False
    return getter(src, dst, ConcernRelationType.ACTIVATES) is not None


def prune_weak_edges(
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    weight_threshold: float = 0.15,
    gate: RewriteGate | None = None,
    beta: float = 0.01,
) -> int:
    view = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)
    pruned = 0
    for edge in view.edges:
        if edge.weight >= weight_threshold:
            continue
        if view.is_conserved(edge.src) or view.is_conserved(edge.dst):
            continue
        objective = score_prune(weight=edge.weight, threshold=weight_threshold, beta=beta)
        if gate is not None and not gate.evaluate("prune", delta_f=objective.delta_f).accepted:
            continue
        dcn_store.remove_edge(edge.src, edge.dst, edge.relation)
        pruned += 1
    return pruned


def lift_coalition(
    *,
    concern_store: ConcernStore,
    members: tuple[str, ...],
    coalition_id: str,
    dcn_store: DCNStore | None = None,
    buffer: ConcernRtBuffer | None = None,
    gate: RewriteGate | None = None,
    beta: float = 0.01,
) -> bool:
    """Lift a co-firing coalition into a higher-order aspect (identity initialization)."""
    if len(members) < 2:
        return False
    parents = [concern_store.get(mid) for mid in members]
    if any(p is None for p in parents):
        return False
    if any(p.reflex for p in parents if p is not None):
        return False
    if concern_store.get(coalition_id) is not None:
        return False
    objective = score_lift(
        coalition_size=len(members),
        reward_mean=_coalition_reward_mean(buffer, members),
        beta=beta,
    )
    if gate is not None and not gate.evaluate("lift", delta_f=objective.delta_f).accepted:
        return False

    keywords: list[str] = []
    joinpoints: set[str] = set()
    for parent in parents:
        assert parent is not None
        keywords.extend(collect_pointcut_keywords(parent))
        for pc in parent.pointcuts:
            for jp in pc.joinpoints or []:
                joinpoints.add(str(jp))

    meta = Concern(
        id=coalition_id,
        name=f"lift({'+'.join(members)})",
        description=f"Aspect-of-aspect lift over {members}",
        pointcuts=[
            PointcutDef(
                id="pc-lift",
                joinpoints=sorted(joinpoints) or ["before_tool_call"],
                match=PointcutMatch(any_keywords=sorted(set(keywords))[:8]),
            )
        ],
        lifecycle_state="created",
        reflex=False,
    )
    concern_store.upsert(meta)
    if dcn_store is not None:
        with suppress(Exception):
            dcn_store.add_node(meta)
        for mid in members:
            parent = concern_store.get(mid)
            if parent is None:
                continue
            with suppress(Exception):
                dcn_store.add_node(parent)
            dcn_store.add_edge(coalition_id, mid, ConcernRelationType.DEPENDS_ON, weight=0.9)
            dcn_store.add_edge(coalition_id, mid, ConcernRelationType.ACTIVATES, weight=0.5)
    return True


def merge_near_duplicate_pair(
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    a_id: str,
    b_id: str,
    buffer: ConcernRtBuffer | None = None,
    gate: RewriteGate | None = None,
    beta: float = 0.01,
) -> bool:
    a = concern_store.get(a_id)
    b = concern_store.get(b_id)
    if a is None or b is None or a.reflex or b.reflex:
        return False
    kw_a = set(collect_pointcut_keywords(a))
    kw_b = set(collect_pointcut_keywords(b))
    overlap = len(kw_a & kw_b)
    if overlap < 2:
        return False
    objective = score_merge(
        keyword_overlap=overlap,
        reward_gap=_reward_gap(buffer, a_id, b_id),
        beta=beta,
    )
    if gate is not None and not gate.evaluate("merge", delta_f=objective.delta_f).accepted:
        return False
    for concern in (a, b):
        with suppress(Exception):
            dcn_store.add_node(concern)
    try:
        dcn_store.merge(b_id, a_id)
    except KeyError:
        return False
    return True


def _reward_mean(buffer: ConcernRtBuffer | None, concern_id: str) -> float | None:
    if buffer is None:
        return None
    samples = buffer.samples(concern_id)
    if not samples:
        return None
    return sum(s.r for s in samples) / len(samples)


def _pair_reward_mean(buffer: ConcernRtBuffer | None, a_id: str, b_id: str) -> float | None:
    means = [m for cid in (a_id, b_id) if (m := _reward_mean(buffer, cid)) is not None]
    if not means:
        return None
    return sum(means) / len(means)


def _coalition_reward_mean(
    buffer: ConcernRtBuffer | None,
    members: tuple[str, ...],
) -> float | None:
    means = [m for cid in members if (m := _reward_mean(buffer, cid)) is not None]
    if not means:
        return None
    return sum(means) / len(means)


def _reward_gap(buffer: ConcernRtBuffer | None, a_id: str, b_id: str) -> float:
    a = _reward_mean(buffer, a_id)
    b = _reward_mean(buffer, b_id)
    if a is None or b is None:
        return 0.0
    return a - b


def split_with_spec_or_keywords(
    *,
    concern: Concern,
    concern_store: ConcernStore,
    buffer: ConcernRtBuffer,
    lifecycle,
    dcn_store: DCNStore | None = None,
    guard: SplitGuardResult | None = None,
) -> bool:
    """Apply paper split when guards pass, else keyword fallback."""

    if concern.reflex or "--" in concern.id:
        return False

    if guard is None:
        guard = evaluate_split_guards(buffer, concern.id)

    proposal = propose_keyword_split(concern)

    if guard.eligible and guard.partition is not None:
        left_kw = [
            s.feature
            for i, s in enumerate(buffer.samples(concern.id))
            if i in guard.partition.left_indices and s.feature
        ]
        right_kw = [
            s.feature
            for i, s in enumerate(buffer.samples(concern.id))
            if i in guard.partition.right_indices and s.feature
        ]
        if left_kw and right_kw:
            from opencoat_runtime_core.credit.connectome_split import SplitProposal

            proposal = SplitProposal(
                parent_id=concern.id,
                child_a_id=f"{concern.id}--a",
                child_b_id=f"{concern.id}--b",
                keywords_a=tuple(sorted(set(left_kw))[:4]),
                keywords_b=tuple(sorted(set(right_kw))[:4]),
            )

    if proposal is None:
        return False

    child_a, child_b = materialize_split(proposal, concern)
    concern_store.upsert(child_a)
    concern_store.upsert(child_b)
    if dcn_store is not None:
        for child in (child_a, child_b):
            with suppress(Exception):
                dcn_store.add_node(child)
    lifecycle.archive(concern, reason="connectome split (ΔF-gated)")
    buffer.clear(concern.id)
    return True


def find_lift_candidates(view: ConnectomeView, min_shared_edges: int = 1) -> list[tuple[str, ...]]:
    """Pairs with mutual ACTIVATES edges — lift coalitions."""
    pairs: list[tuple[str, str]] = []
    for edge in view.edges:
        if edge.relation != ConcernRelationType.ACTIVATES:
            continue
        pairs.append((edge.src, edge.dst))
    coalitions: list[tuple[str, ...]] = []
    for a, b in pairs:
        if (b, a) in pairs:
            coalitions.append(tuple(sorted((a, b))))
    return list(dict.fromkeys(coalitions))


def find_merge_candidates(view: ConnectomeView) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    ids = [cid for cid, c in view.aspects.items() if not c.reflex]
    for a, b in combinations(sorted(ids), 2):
        ca = set(collect_pointcut_keywords(view.aspects[a]))
        cb = set(collect_pointcut_keywords(view.aspects[b]))
        if len(ca & cb) >= 2:
            out.append((a, b))
    return out


__all__ = [
    "ConnectomeRewriteStats",
    "connect_coactivated",
    "find_lift_candidates",
    "find_merge_candidates",
    "lift_coalition",
    "merge_near_duplicate_pair",
    "prune_weak_edges",
    "split_with_spec_or_keywords",
]
