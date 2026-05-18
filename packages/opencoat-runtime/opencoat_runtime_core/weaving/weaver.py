"""Concern Weaver — builds the per-turn :class:`ConcernInjection` payload.

The weaver is the *only* module allowed to materialise the wire-format
:class:`ConcernInjection`. It walks the coordinator's :class:`ConcernVector`
and, for each active concern, resolves:

* **target** — where the advice lands (e.g. ``runtime_prompt.verification_rules``).
* **mode**   — which of the 11 weaving operations (insert / verify / block …).
* **level**  — which of the 8 weaving levels (prompt / tool / output …).
* **content** — the rendered advice text, truncated to the budget.

Resolution order for each field is **policy → defaults**: if
``concern.weaving_policy`` pins a value, the weaver honours it; otherwise
the per-advice-type defaults from :mod:`._defaults` apply.

Determinism / safety properties:

* Output is sorted by ``(-priority, concern_id, target)`` so two runs
  on the same vector produce identical bytes.
* Active concerns missing from the ``concerns`` / ``advices`` maps are
  *skipped*, not raised — the coordinator already cleared budgets
  upstream and a dropped advice should not crash a turn.
* The total token estimate honours the runtime ``max_injection_tokens``
  cap; trailing injections are dropped (cutoff, not bin-pack — the same
  contract the coordinator uses).
* A per-injection cap (``WeavingPolicy.max_tokens``, default 200, or
  ``Advice.max_tokens`` if smaller) trims the content body before the
  global budget is applied.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    ConcernInjection,
    ConcernVector,
    WeavingLevel,
    WeavingOperation,
)
from opencoat_runtime_protocol.envelopes import (
    ActiveConcern,
    Injection,
    InjectionTotals,
    WeavingPolicy,
)

from ..config import RuntimeBudgets
from ._defaults import DEFAULT_LEVEL, DEFAULT_MODE, DEFAULT_TARGET

# Same heuristic the coordinator's BudgetController uses; centralising the
# constant keeps the two budget gates aligned.
_AVG_CHARS_PER_TOKEN = 4


class ConcernWeaver:
    """Compose advice + weaving policies into a single Concern Injection.

    The weaver enforces token / count budgets and is the only module allowed
    to materialise the host-consumable :class:`ConcernInjection` shape.
    """

    def __init__(self, *, budgets: RuntimeBudgets) -> None:
        self._budgets = budgets

    def build(
        self,
        *,
        weave_id: str,
        host_round_id: str | None = None,
        vector: ConcernVector,
        concerns: dict[str, Concern],
        advices: dict[str, Advice],
    ) -> ConcernInjection:
        # We carry (vector_index, activation_score, injection) so the sort
        # can preserve the coordinator's ranked order (its activation_score
        # is the *primary* signal). Without this the cutoff in
        # ``_enforce_budget`` could drop a coordinator-top concern whose
        # weaving_policy.priority happens to be unset while keeping a
        # lower-ranked one with an explicit higher policy priority — a
        # silent ranking inversion across the pipeline boundary.
        candidates: list[tuple[int, float, Injection]] = []
        for index, active in enumerate(vector.active_concerns):
            concern = concerns.get(active.concern_id)
            advice = advices.get(active.concern_id)
            if concern is None or advice is None:
                continue
            injection = self._render_one(active, concern, advice)
            if injection is None:
                continue
            candidates.append((index, active.activation_score, injection))

        # Sort key: highest activation_score first (the coordinator's
        # truth), then highest weaving priority, then the coordinator's
        # original index (stable preservation of ties), then concern_id /
        # target for full determinism.
        candidates.sort(
            key=lambda triple: (
                -triple[1],
                -(triple[2].priority if triple[2].priority is not None else 0.0),
                triple[0],
                triple[2].concern_id,
                triple[2].target,
            )
        )
        ordered = [inj for _, _, inj in candidates]
        kept, totals = self._enforce_budget(ordered)

        return ConcernInjection(
            weave_id=weave_id,
            host_round_id=host_round_id or vector.host_round_id,
            agent_session_id=vector.agent_session_id,
            ts=datetime.now(UTC),
            injections=kept,
            totals=totals,
        )

    def empty(
        self,
        weave_id: str,
        vector: ConcernVector | None = None,
        *,
        host_round_id: str | None = None,
    ) -> ConcernInjection:
        return ConcernInjection(
            weave_id=weave_id,
            host_round_id=host_round_id
            if host_round_id is not None
            else (vector.host_round_id if vector is not None else None),
            agent_session_id=vector.agent_session_id if vector is not None else None,
            ts=datetime.now(UTC),
            injections=[],
            totals=InjectionTotals(),
        )

    # ------------------------------------------------------------------
    # Per-concern rendering
    # ------------------------------------------------------------------

    def _render_one(
        self,
        active: ActiveConcern,
        concern: Concern,
        advice: Advice,
    ) -> Injection | None:
        from ..concern.executable import primary_weaving

        policy = primary_weaving(concern) or WeavingPolicy()
        advice_type = AdviceType(advice.type)

        target = policy.target or DEFAULT_TARGET[advice_type]
        mode = WeavingOperation(policy.mode) if policy.mode else DEFAULT_MODE[advice_type]
        level = WeavingLevel(policy.level) if policy.level else DEFAULT_LEVEL[advice_type]

        content = self._truncate(advice, policy)
        if not content:
            return None

        priority = active.priority if active.priority is not None else policy.priority
        return Injection(
            concern_id=concern.id,
            advice_type=advice_type,
            target=target,
            mode=mode,
            level=level,
            content=content,
            priority=priority,
        )

    @staticmethod
    def _truncate(advice: Advice, policy: WeavingPolicy) -> str:
        body = advice.content
        if not body:
            return ""

        cap_tokens = policy.max_tokens
        if advice.max_tokens is not None:
            cap_tokens = min(cap_tokens, advice.max_tokens)

        char_cap = max(cap_tokens * _AVG_CHARS_PER_TOKEN, 1)
        if len(body) <= char_cap:
            return body
        # Trim on a word boundary if possible to avoid mid-word cuts.
        cut = body.rfind(" ", 0, char_cap)
        if cut <= char_cap // 2:
            cut = char_cap
        return body[:cut].rstrip() + "…"

    # ------------------------------------------------------------------
    # Global budget enforcement
    # ------------------------------------------------------------------

    def _enforce_budget(
        self,
        ordered: list[Injection],
    ) -> tuple[list[Injection], InjectionTotals]:
        max_tokens = self._budgets.max_injection_tokens
        max_concerns = self._budgets.max_active_concerns

        kept: list[Injection] = []
        used_tokens = 0
        seen_concerns: set[str] = set()
        for inj in ordered:
            cost = self._token_cost(inj.content)
            # Cutoff: once a higher-ranked injection cannot fit, do not
            # promote a smaller, lower-ranked one in its place — that
            # would invert the weaver's deterministic ordering. The
            # first injection is always admitted so a single oversized
            # advice never empties the turn.
            if kept and used_tokens + cost > max_tokens:
                break
            if len(seen_concerns) >= max_concerns and inj.concern_id not in seen_concerns:
                break
            kept.append(inj)
            used_tokens += cost
            seen_concerns.add(inj.concern_id)

        totals = InjectionTotals(
            tokens=used_tokens,
            concern_count=len(seen_concerns),
            advice_count=len(kept),
        )
        return kept, totals

    @staticmethod
    def _token_cost(content: str) -> int:
        if not content:
            return 0
        return max(
            1,
            (len(content) + _AVG_CHARS_PER_TOKEN - 1) // _AVG_CHARS_PER_TOKEN,
        )


__all__ = ["ConcernWeaver"]
