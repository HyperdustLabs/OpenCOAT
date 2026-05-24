"""Effector kernel — one-turn propose → mediate → verify/repair → ``r_t`` (v0.3 §3.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from opencoat_runtime_protocol import ConcernInjection, JoinpointEvent

from ..concern.reflex_policy_export import export_reflex_policies
from ..credit.r_t_record import RtRecord, RtSignal, reward_from_signal
from ..loops.joinpoint_pipeline import JoinpointPipeline
from ..ports import ConcernStore
from .reflex_monitor import EffectorAction, EffectorState, ReflexMonitor

ActionKind = Literal[
    "tool_call",
    "spawn",
    "message_out",
    "queue_enqueue",
    "memory_write",
    "tool_result_persist",
]


@dataclass(frozen=True)
class EffectorOutcome:
    """Deterministic result of ``run_turn`` for replay / credit assignment."""

    allowed: bool
    action: EffectorAction
    decision: Literal["allow", "deny", "rewrite"]
    injection: ConcernInjection | None
    record: RtRecord
    repair_attempts: int = 0
    policy_id: str | None = None
    reason: str | None = None


class EffectorKernel:
    """Prototype ``⇩_fast`` turn loop wiring weave + in-proc reflex + ``r_t`` emit."""

    DEFAULT_MAX_REPAIR = 1

    def __init__(
        self,
        *,
        pipeline: JoinpointPipeline,
        concern_store: ConcernStore,
        monitor: ReflexMonitor | None = None,
        max_repair: int = DEFAULT_MAX_REPAIR,
        host: str = "effector",
    ) -> None:
        self._pipeline = pipeline
        self._concern_store = concern_store
        self._monitor = monitor
        self._max_repair = max(0, max_repair)
        self._host = host

    def _resolve_monitor(self) -> ReflexMonitor:
        if self._monitor is not None:
            return self._monitor
        export = export_reflex_policies(
            list(self._concern_store.iter_all()),
            action_kind="all",
        )
        return ReflexMonitor.from_export(export)

    def run_turn(
        self,
        joinpoint: JoinpointEvent,
        action: EffectorAction,
        *,
        context: dict[str, Any] | None = None,
        session_id: str = "default",
        turn_id: str | None = None,
    ) -> EffectorOutcome:
        """Route → propose (weave) → mediate → verify/repair → ``r_t``."""
        resolved_turn = turn_id or joinpoint.host_round_id or joinpoint.id
        state = EffectorState(
            session_id=session_id,
            turn_id=resolved_turn,
            features={"joinpoint": joinpoint.name},
        )

        injection = self._pipeline.run(
            joinpoint,
            context=context,
            return_none_when_empty=True,
        )

        monitor = self._resolve_monitor()
        current = action
        decision_kind: Literal["allow", "deny", "rewrite"] = "allow"
        policy_id: str | None = None
        reason: str | None = None
        repair_attempts = 0

        for attempt in range(self._max_repair + 1):
            reflex_decision, record = monitor.mediate(current, state)
            record = record.__class__(
                turn_id=resolved_turn,
                action_kind=record.action_kind,
                action_name=record.action_name,
                decision=record.decision,
                policy_id=record.policy_id,
                reason=record.reason,
                criticality=record.criticality,
            )
            if reflex_decision.kind == "allow":
                decision_kind = "allow"
                break
            if reflex_decision.kind == "deny":
                decision_kind = "deny"
                policy_id = reflex_decision.policy_id
                reason = reflex_decision.reason
                break
            if reflex_decision.kind == "rewrite" and reflex_decision.action is not None:
                decision_kind = "rewrite"
                policy_id = reflex_decision.policy_id
                reason = reflex_decision.reason
                current = reflex_decision.action
                repair_attempts = attempt + 1
                break

        allowed = decision_kind != "deny"
        signal = self._build_signal(
            action=current,
            allowed=allowed,
            decision=decision_kind,
            policy_id=policy_id,
        )
        rt = RtRecord(
            ts=datetime.now(tz=UTC),
            session_id=session_id,
            turn_id=resolved_turn,
            joinpoint=joinpoint.name,
            host=self._host,
            hook=joinpoint.name,
            signal=signal,
            r=reward_from_signal(signal),
            baseline_b=0.0,
        )
        return EffectorOutcome(
            allowed=allowed,
            action=current,
            decision=decision_kind,
            injection=injection,
            record=rt,
            repair_attempts=repair_attempts,
            policy_id=policy_id,
            reason=reason,
        )

    def _build_signal(
        self,
        *,
        action: EffectorAction,
        allowed: bool,
        decision: str,
        policy_id: str | None,
    ) -> RtSignal:
        reflex = {
            "policy_id": policy_id,
            "decision": decision,
        }
        if action.kind == "tool_call":
            if not allowed:
                return RtSignal(
                    kind="tool_blocked",
                    tool_name=action.name,
                    blocked=True,
                    reflex=reflex,
                )
            return RtSignal(
                kind="tool_outcome",
                tool_name=action.name,
                blocked=False,
                reflex=reflex,
                payload={"arguments": action.args},
            )
        return RtSignal(
            kind="reflex_decision",
            reflex=reflex,
            payload={"action_kind": action.kind, "allowed": allowed},
        )


__all__ = ["EffectorKernel", "EffectorOutcome"]
