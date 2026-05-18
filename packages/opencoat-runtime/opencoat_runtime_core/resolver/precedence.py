"""AOP (AspectJ) ``declare precedence`` resolution (ADR-0010).

Builds a winner-over-loser map from ``Concern.declarations`` and
``declares_precedence_over`` relations, then drops lower-precedence concerns
when both appear in the same ranked activation set.
"""

from __future__ import annotations

from collections import defaultdict

from opencoat_runtime_protocol import Concern, ConcernRelationType
from opencoat_runtime_protocol.envelopes import DeclarePrecedence


def build_precedence_beats(concerns: list[Concern]) -> dict[str, set[str]]:
    """Map each higher-precedence concern id to ids it defeats."""
    beats: dict[str, set[str]] = defaultdict(set)
    for concern in concerns:
        for decl in concern.declarations:
            if not isinstance(decl, DeclarePrecedence):
                continue
            order = decl.order
            for i, winner in enumerate(order):
                for loser in order[i + 1 :]:
                    if winner != loser:
                        beats[winner].add(loser)
        for rel in concern.relations:
            if rel.relation_type == ConcernRelationType.DECLARES_PRECEDENCE_OVER:
                beats[concern.id].add(rel.target_concern_id)
    return dict(beats)


def precedence_drops(
    ranked: list[tuple[Concern, float]],
    beats: dict[str, set[str]],
) -> set[str]:
    """Return concern ids to drop because a higher-precedence peer activated."""
    active = {c.id for c, _ in ranked}
    dropped: set[str] = set()
    for winner, losers in beats.items():
        if winner not in active or winner in dropped:
            continue
        for loser in losers:
            if loser in active and loser not in dropped:
                dropped.add(loser)
    return dropped


__all__ = ["build_precedence_beats", "precedence_drops"]
