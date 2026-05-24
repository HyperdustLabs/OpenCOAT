"""Connectome plasticity primitives: connect / prune / lift / merge (v0.3 §3.6)."""

from __future__ import annotations

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
from opencoat_runtime_core.credit.split_spec import SplitGuardResult, evaluate_split_guards
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
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
) -> int:
    """Add / strengthen ACTIVATES edges for co-activated concern pairs."""
    added = 0
    view = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)
    for a, b in co_pairs:
        if a == b or view.is_conserved(a) or view.is_conserved(b):
            continue
        if a not in view.aspects or b not in view.aspects:
            continue
        dcn_store.add_edge(a, b, ConcernRelationType.ACTIVATES, weight=min_weight)
        added += 1
    return added


def prune_weak_edges(
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    weight_threshold: float = 0.15,
) -> int:
    view = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)
    pruned = 0
    for edge in view.edges:
        if edge.weight >= weight_threshold:
            continue
        if view.is_conserved(edge.src) or view.is_conserved(edge.dst):
            continue
        dcn_store.remove_edge(edge.src, edge.dst, edge.relation)
        pruned += 1
    return pruned


def lift_coalition(
    *,
    concern_store: ConcernStore,
    members: tuple[str, ...],
    coalition_id: str,
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
    return True


def merge_near_duplicate_pair(
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    a_id: str,
    b_id: str,
) -> bool:
    a = concern_store.get(a_id)
    b = concern_store.get(b_id)
    if a is None or b is None or a.reflex or b.reflex:
        return False
    kw_a = set(collect_pointcut_keywords(a))
    kw_b = set(collect_pointcut_keywords(b))
    if len(kw_a & kw_b) < 2:
        return False
    dcn_store.merge(b_id, a_id)
    return True


def split_with_spec_or_keywords(
    *,
    concern: Concern,
    concern_store: ConcernStore,
    buffer: ConcernRtBuffer,
    lifecycle,
    guard: SplitGuardResult | None = None,
) -> bool:
    """Apply paper split when guards pass, else keyword fallback."""
    from opencoat_runtime_core.credit.connectome_split import propose_keyword_split

    if concern.reflex or "--" in concern.id:
        return False

    if guard is None:
        guard = evaluate_split_guards(buffer, concern.id)

    proposal = propose_keyword_split(concern)
    if proposal is None:
        return False

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
                keywords_a=tuple(sorted(set(left_kw))[:4] or proposal.keywords_a),
                keywords_b=tuple(sorted(set(right_kw))[:4] or proposal.keywords_b),
            )

    child_a, child_b = materialize_split(proposal, concern)
    concern_store.upsert(child_a)
    concern_store.upsert(child_b)
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
