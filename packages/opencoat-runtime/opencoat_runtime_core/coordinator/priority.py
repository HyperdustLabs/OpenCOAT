"""Priority ranker — combines relevance / priority / trust / recency / history.

The matcher (PR-2) hands the coordinator a list of ``(concern, relevance)``
tuples. The ranker turns those into a *composite activation score* by
folding in per-concern signals carried by the :class:`Concern` envelope.

Default formula (v0.1 §18, simplified for M1):

    activation = w_r · relevance
               + w_p · concern.activation_state.priority   (proxied below)
               + w_t · source.trust
               + w_h · history_effectiveness
               - w_c · conflict_penalty

Weights default to ``1.0`` so callers can override without re-deriving the
arithmetic. Output is clamped to ``[0, 1]``. Sort is stable by ``-score``
then by ``concern.id`` so the ranking is fully deterministic — important
because the resolver (and downstream weaver) consume this list directly.

M1 keeps the ranker fully synchronous and free of external lookups; the
DCN-derived ``history_effectiveness`` and ``conflict_penalty`` signals are
read from the runtime ``context`` map when available. Wiring those signals
through the coordinator is the turn-loop PR's responsibility (PR-5).
"""

from __future__ import annotations

from dataclasses import dataclass

from opencoat_runtime_protocol import Concern

from ._util import clamp01


@dataclass(frozen=True)
class RankWeights:
    """Coefficients used by :class:`PriorityRanker.rank`."""

    relevance: float = 1.0
    priority: float = 0.5
    trust: float = 0.3
    history: float = 0.2
    conflict_penalty: float = 0.5

    def total(self) -> float:
        """Sum of positive coefficients used for normalisation."""
        return self.relevance + self.priority + self.trust + self.history


class PriorityRanker:
    """Combine matcher relevance with per-concern signals into one score."""

    def __init__(self, weights: RankWeights | None = None) -> None:
        self._weights = weights or RankWeights()

    def rank(
        self,
        scored: list[tuple[Concern, float]],
        *,
        context: dict | None = None,
    ) -> list[tuple[Concern, float]]:
        history = (context or {}).get("history_effectiveness", {}) or {}
        conflicts = (context or {}).get("conflict_penalty", {}) or {}

        result: list[tuple[Concern, float]] = []
        for concern, relevance in scored:
            composite = self._compose(concern, relevance, history, conflicts)
            result.append((concern, composite))

        result.sort(key=lambda pair: (-pair[1], pair[0].id))
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compose(
        self,
        concern: Concern,
        relevance: float,
        history: dict,
        conflicts: dict,
    ) -> float:
        w = self._weights
        priority = self._priority_signal(concern)
        trust = self._trust_signal(concern)
        history_eff = clamp01(history.get(concern.id, 0.0))
        conflict_penalty = clamp01(conflicts.get(concern.id, 0.0))

        weighted = (
            w.relevance * clamp01(relevance)
            + w.priority * priority
            + w.trust * trust
            + w.history * history_eff
            - w.conflict_penalty * conflict_penalty
        )
        denominator = w.total()
        normalised = weighted / denominator if denominator > 0 else 0.0
        return clamp01(normalised)

    @staticmethod
    def _priority_signal(concern: Concern) -> float:
        from ..concern.executable import primary_weaving

        weaving = primary_weaving(concern)
        if weaving is not None:
            return clamp01(weaving.priority)
        return 0.5  # neutral default

    @staticmethod
    def _trust_signal(concern: Concern) -> float:
        if concern.source is not None and concern.source.trust is not None:
            return clamp01(concern.source.trust)
        return 0.5  # neutral default


__all__ = ["PriorityRanker", "RankWeights"]
