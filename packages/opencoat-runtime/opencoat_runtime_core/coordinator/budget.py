"""Budget controller — enforces token / count caps from :class:`RuntimeBudgets`.

The controller is a **ranking-preserving cutoff**: it walks the ranked
list in order and stops as soon as either budget would be violated.
There is no bin-packing — admitting a smaller, lower-ranked concern
in place of a dropped higher-ranked one would silently invert the
ranking that the rest of the pipeline (ranker, top-k) is designed to
preserve.

Budgets enforced:

* ``max_active_concerns`` — hard cap on the number of activations.
* ``max_injection_tokens`` — soft cap derived from per-concern token
  estimates (advice ``content`` + ``rationale`` length, divided by an
  average characters-per-token ratio). The first entry is always allowed
  even if it alone exceeds the budget; otherwise a single oversized
  concern would silently drop the whole turn's vector.

This is intentionally a *deterministic, last-resort* gate. Cheaper culling
(e.g. priority/relevance dropoff) is the ranker's job.
"""

from __future__ import annotations

from opencoat_runtime_protocol import Concern

from ..config import RuntimeBudgets

# Rough average for English / mixed-language text. Hosts that need a real
# tokenizer can subclass and override :meth:`estimate_tokens`.
_AVG_CHARS_PER_TOKEN = 4


class BudgetController:
    """Cap a ranked list of concerns by count and estimated token cost."""

    def __init__(self, *, budgets: RuntimeBudgets) -> None:
        self._budgets = budgets

    def enforce(
        self,
        ranked: list[tuple[Concern, float]],
    ) -> list[tuple[Concern, float]]:
        max_count = self._budgets.max_active_concerns
        max_tokens = self._budgets.max_injection_tokens

        kept: list[tuple[Concern, float]] = []
        used_tokens = 0
        for concern, score in ranked:
            if len(kept) >= max_count:
                break
            cost = self.estimate_tokens(concern)
            # Cutoff, not bin-pack: once a higher-ranked concern won't
            # fit, do not promote a smaller, lower-ranked one in its
            # place — that would invert the ranking. The first entry
            # is always admitted (``not kept``) so an oversized top
            # concern never empties the vector.
            if kept and used_tokens + cost > max_tokens:
                break
            kept.append((concern, score))
            used_tokens += cost
        return kept

    def estimate_tokens(self, concern: Concern) -> int:
        """Estimate the token cost of injecting *concern*.

        We look only at the ``advice`` payload because that is what reaches
        the prompt; the rest of the envelope is metadata and never hits
        the LLM. The estimate is an upper bound on what the weaver might
        emit — better to undershoot the budget than to truncate prompts.
        """
        from ..concern.executable import primary_advice

        advice = primary_advice(concern)
        if advice is None:
            return 0
        chars = len(advice.content)
        if advice.rationale:
            chars += len(advice.rationale)
        if chars <= 0:
            return 0
        cap = advice.max_tokens
        # ceiling division
        estimated = (chars + _AVG_CHARS_PER_TOKEN - 1) // _AVG_CHARS_PER_TOKEN
        if cap is not None:
            estimated = min(estimated, cap)
        return max(estimated, 1)


__all__ = ["BudgetController"]
