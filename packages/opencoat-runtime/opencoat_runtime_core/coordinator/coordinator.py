"""Concern Coordinator — v0.1 §20.7.

Builds the per-turn :class:`ConcernVector` by orchestrating, in order:

1. :class:`PriorityRanker`   — composite activation score
2. :class:`ConcernResolver`  — dedupe + conflict resolution + escalation
3. :class:`BudgetController` — token / count enforcement
4. :class:`TopKSelector`     — final cap by ``budgets.max_active_concerns``
5. :class:`ConcernVectorBuilder` — schema-validated envelope

Steps 3 and 4 are both gates on count: budget is the *substantive* one
(tokens + count), top-k is a final ceiling. They are kept separate so
the budget can apply token caps without re-implementing top-k logic.

The coordinator is intentionally synchronous and side-effect-free except
for the resolver's escalation side-channel, which it exposes as a
read-only property for the joinpoint pipeline to consume.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opencoat_runtime_protocol import Concern, ConcernVector, JoinpointEvent
from opencoat_runtime_protocol.envelopes import ActiveConcern

from ..concern.vector import ConcernVectorBuilder
from ..config import RuntimeBudgets
from ..resolver import ConcernResolver
from ._util import clamp01
from .budget import BudgetController
from .priority import PriorityRanker
from .topk import TopKSelector


class ConcernCoordinator:
    def __init__(
        self,
        *,
        budgets: RuntimeBudgets,
        vector_builder: ConcernVectorBuilder | None = None,
        topk: TopKSelector | None = None,
        priority: PriorityRanker | None = None,
        budget_controller: BudgetController | None = None,
        resolver: ConcernResolver | None = None,
    ) -> None:
        self._budgets = budgets
        self._vector_builder = vector_builder or ConcernVectorBuilder(budgets=budgets)
        self._topk = topk or TopKSelector()
        self._priority = priority or PriorityRanker()
        self._budget = budget_controller or BudgetController(budgets=budgets)
        self._resolver = resolver or ConcernResolver()
        self._last_escalations: list[dict[str, Any]] = []

    def coordinate(
        self,
        *,
        weave_id: str,
        host_round_id: str | None = None,
        candidates: list[tuple[Concern, float]],
        joinpoint: JoinpointEvent,
        context: dict | None = None,
    ) -> ConcernVector:
        if not candidates:
            self._last_escalations = []
            return self._vector_builder.empty(weave_id, host_round_id=host_round_id)

        ranked = self._priority.rank(candidates, context=context)
        resolved = self._resolver.resolve(ranked)
        self._last_escalations = list(self._resolver.last_escalations)

        budgeted = self._budget.enforce(resolved)
        capped = self._topk.select(budgeted, self._budgets.max_active_concerns)

        active = [self._to_active(concern, score, joinpoint) for concern, score in capped]
        return self._vector_builder.build(
            weave_id=weave_id,
            host_round_id=host_round_id,
            agent_session_id=joinpoint.agent_session_id,
            active=active,
            ts=datetime.now(UTC),
        )

    @property
    def last_escalations(self) -> list[dict[str, Any]]:
        """Escalation payloads from the most recent :meth:`coordinate` call."""
        return list(self._last_escalations)

    @staticmethod
    def _to_active(
        concern: Concern,
        score: float,
        joinpoint: JoinpointEvent,
    ) -> ActiveConcern:
        priority = concern.weaving_policy.priority if concern.weaving_policy is not None else None
        confidence = (
            concern.activation_state.score
            if concern.activation_state is not None and concern.activation_state.score is not None
            else None
        )
        injection_mode = concern.advice.type if concern.advice is not None else None
        return ActiveConcern(
            concern_id=concern.id,
            activation_score=clamp01(score),
            priority=priority,
            confidence=confidence,
            injection_mode=injection_mode,
            matched_joinpoint=joinpoint.name,
        )
