"""Concern conflict resolver.

Uses two of the canonical relation types:

* ``conflicts_with`` — symmetric: both sides cannot fire together. The
  higher-scoring concern wins; ties are broken by ``concern.id`` so the
  outcome is deterministic.
* ``declares_precedence_over`` / ``declare precedence`` — AOP (AspectJ) ordering:
  the higher-precedence concern wins when both are activated (score ignored).
* ``suppresses`` — directional (legacy): the source concern silences the
  target whenever both are activated, regardless of score.

Both rules drop the loser entirely from the ranked list. Soft penalties
(score reduction) are the ranker's responsibility.
"""

from __future__ import annotations

from collections.abc import Sequence

from opencoat_runtime_protocol import Concern, ConcernRelationType

from .precedence import build_precedence_beats, precedence_drops


class ConflictResolver:
    """Detect and resolve hard conflicts on a ranked list."""

    def detect(self, concerns: list[Concern]) -> list[tuple[Concern, Concern]]:
        index = {c.id: c for c in concerns}
        seen: set[tuple[str, str]] = set()
        conflicts: list[tuple[Concern, Concern]] = []
        for concern in concerns:
            for rel in concern.relations:
                if rel.relation_type != ConcernRelationType.CONFLICTS_WITH:
                    continue
                target = index.get(rel.target_concern_id)
                if target is None:
                    continue
                key = tuple(sorted((concern.id, target.id)))
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append((concern, target))
        return conflicts

    def resolve(
        self,
        ranked: list[tuple[Concern, float]],
        *,
        concern_catalog: Sequence[Concern] | None = None,
    ) -> list[tuple[Concern, float]]:
        if not ranked:
            return []

        scores = {c.id: s for c, s in ranked}
        dropped: set[str] = set()

        # 1. AOP declare precedence (AspectJ) — rules from full catalog, applied to active set.
        catalog = list(concern_catalog) if concern_catalog is not None else [c for c, _ in ranked]
        beats = build_precedence_beats(catalog)
        dropped |= precedence_drops(ranked, beats)

        # 2. Hard suppression: directional ``suppresses`` always wins.
        for concern, _ in ranked:
            if concern.id in dropped:
                continue
            for rel in concern.relations:
                if rel.relation_type != ConcernRelationType.SUPPRESSES:
                    continue
                if rel.target_concern_id in scores:
                    dropped.add(rel.target_concern_id)

        # 3. Symmetric conflicts: keep the better score (id is tiebreaker).
        for concern, _ in ranked:
            if concern.id in dropped:
                continue
            for rel in concern.relations:
                if rel.relation_type != ConcernRelationType.CONFLICTS_WITH:
                    continue
                target_id = rel.target_concern_id
                if target_id not in scores or target_id in dropped:
                    continue
                loser = self._pick_loser(concern.id, target_id, scores)
                dropped.add(loser)
                if loser == concern.id:
                    break

        return [(c, s) for c, s in ranked if c.id not in dropped]

    @staticmethod
    def _pick_loser(a_id: str, b_id: str, scores: dict[str, float]) -> str:
        a_score = scores[a_id]
        b_score = scores[b_id]
        if a_score > b_score:
            return b_id
        if b_score > a_score:
            return a_id
        # deterministic tiebreaker: drop the lexicographically larger id
        return max(a_id, b_id)


__all__ = ["ConflictResolver"]
