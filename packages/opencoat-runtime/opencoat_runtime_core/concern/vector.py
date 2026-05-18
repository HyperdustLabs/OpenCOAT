"""Concern Vector builder — v0.1 §17.

A Concern Vector is **not** a dense embedding — it is the sparse
*activation snapshot* of the DCN for the current turn (set of active
concerns + per-concern weights).

This module is the single place that turns the coordinator's output into
the schema-validated :class:`ConcernVector` envelope. Keeping the
construction here means the coordinator does not need to know the wire
format and tests can verify the mapping in isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_protocol import ConcernVector
from opencoat_runtime_protocol.envelopes import ActiveConcern, VectorBudget

from ..config import RuntimeBudgets


class ConcernVectorBuilder:
    """Assemble a :class:`ConcernVector` from coordinator output."""

    def __init__(self, *, budgets: RuntimeBudgets) -> None:
        self._budgets = budgets

    def build(
        self,
        *,
        weave_id: str,
        host_round_id: str | None = None,
        agent_session_id: str | None = None,
        active: list[ActiveConcern],
        ts: datetime | None = None,
    ) -> ConcernVector:
        return ConcernVector(
            weave_id=weave_id,
            host_round_id=host_round_id,
            agent_session_id=agent_session_id,
            ts=ts or datetime.now(UTC),
            active_concerns=list(active),
            budget=self._budget_envelope(),
        )

    def empty(self, weave_id: str, *, host_round_id: str | None = None) -> ConcernVector:
        return ConcernVector(
            weave_id=weave_id,
            host_round_id=host_round_id,
            ts=datetime.now(UTC),
            active_concerns=[],
            budget=self._budget_envelope(),
        )

    def _budget_envelope(self) -> VectorBudget:
        return VectorBudget(
            max_active_concerns=self._budgets.max_active_concerns,
            max_injection_tokens=self._budgets.max_injection_tokens,
        )
