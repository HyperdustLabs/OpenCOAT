"""In-proc reflex monitor (Python TCB mirror of bridge ``reflex-monitor.ts``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

ReflexCriticality = Literal["safety_critical", "advisory"]
ActionKind = Literal[
    "tool_call",
    "spawn",
    "message_out",
    "queue_enqueue",
    "memory_write",
    "tool_result_persist",
]
DecisionKind = Literal["allow", "deny", "rewrite"]


@dataclass(frozen=True)
class EffectorAction:
    kind: ActionKind
    name: str
    args: dict[str, Any]
    raw: Any | None = None


@dataclass(frozen=True)
class EffectorState:
    session_id: str
    turn_id: str
    features: dict[str, Any]


@dataclass(frozen=True)
class ReflexDecision:
    kind: DecisionKind
    policy_id: str | None = None
    reason: str | None = None
    action: EffectorAction | None = None


@dataclass(frozen=True)
class ReflexDecisionRecord:
    turn_id: str
    action_kind: ActionKind
    action_name: str
    decision: DecisionKind
    policy_id: str | None = None
    reason: str | None = None
    criticality: ReflexCriticality | None = None


def _serialize_args(args: dict[str, Any]) -> str:
    try:
        return json.dumps(args, sort_keys=True)
    except TypeError:
        return str(args)


def _args_contains(action: EffectorAction, needles: list[str], *, case_insensitive: bool) -> bool:
    hay = _serialize_args(action.args)
    if case_insensitive:
        hay = hay.lower()
    for needle in needles:
        n = needle.lower() if case_insensitive else needle
        if n in hay:
            return True
    return False


@dataclass(frozen=True)
class _ReflexPolicy:
    id: str
    criticality: ReflexCriticality
    action_kind: ActionKind
    predicate_kind: str
    needles: tuple[str, ...]
    tool_names: tuple[str, ...]
    case_insensitive: bool
    effect: Literal["deny", "rewrite"]
    deny_reason: str
    rewrite_content: str | None


class ReflexMonitor:
    """Pure synchronous policy evaluator for ``EffectorKernel``."""

    _RANK: ClassVar[dict[str, int]] = {"allow": 1, "rewrite": 2, "deny": 3}

    def __init__(
        self,
        policies: list[_ReflexPolicy],
        *,
        conserved_core: frozenset[str] | None = None,
    ) -> None:
        self._policies = sorted(policies, key=lambda p: p.id)
        self._conserved_core = conserved_core or frozenset()

    @classmethod
    def from_export(cls, export: dict[str, Any]) -> ReflexMonitor:
        policies: list[_ReflexPolicy] = []
        for row in export.get("policies") or []:
            if not isinstance(row, dict):
                continue
            pred = row.get("predicate") or {}
            if not isinstance(pred, dict):
                continue
            kind = pred.get("kind")
            needles: tuple[str, ...] = ()
            tool_names: tuple[str, ...] = ()
            if kind in {"args_contains", "text_contains"} and isinstance(pred.get("needles"), list):
                needles = tuple(str(n) for n in pred["needles"] if n)
            elif kind == "tool_name" and isinstance(pred.get("names"), list):
                tool_names = tuple(str(n) for n in pred["names"] if n)
            else:
                continue
            action_kind = row.get("action_kind")
            if action_kind not in {
                "tool_call",
                "spawn",
                "message_out",
                "queue_enqueue",
                "memory_write",
                "tool_result_persist",
            }:
                continue
            effect = row.get("effect", "deny")
            if effect not in {"deny", "rewrite"}:
                effect = "deny"
            rewrite_content = row.get("rewrite_content")
            if isinstance(rewrite_content, str):
                rewrite_content = rewrite_content.strip() or None
            else:
                rewrite_content = None
            if effect == "rewrite" and not rewrite_content:
                continue
            policies.append(
                _ReflexPolicy(
                    id=str(row["id"]),
                    criticality=row.get("criticality", "safety_critical"),
                    action_kind=action_kind,
                    predicate_kind=str(kind),
                    needles=needles,
                    tool_names=tool_names,
                    case_insensitive=pred.get("case_insensitive") is True,
                    effect=effect,
                    deny_reason=str(row.get("deny_reason", "")),
                    rewrite_content=rewrite_content,
                )
            )
        conserved = frozenset(p.id for p in policies if p.criticality == "safety_critical")
        return cls(policies, conserved_core=conserved)

    def mediate(
        self,
        action: EffectorAction,
        state: EffectorState,
    ) -> tuple[ReflexDecision, ReflexDecisionRecord]:
        del state
        decision = ReflexDecision(kind="allow")
        winning: _ReflexPolicy | None = None

        for policy in self._policies:
            try:
                if not self._applies(policy, action):
                    continue
                next_dec = self._decide(policy, action)
                if next_dec.kind == "allow":
                    continue
                if self._RANK[next_dec.kind] >= self._RANK[decision.kind]:
                    decision = next_dec
                    winning = policy
            except Exception as err:
                if policy.criticality == "safety_critical":
                    reason = str(err) or "Reflex policy evaluation failed"
                    deny = ReflexDecision(
                        kind="deny",
                        policy_id=policy.id,
                        reason=reason,
                    )
                    return deny, self._record(action, deny, policy)
        return decision, self._record(action, decision, winning)

    def _applies(self, policy: _ReflexPolicy, action: EffectorAction) -> bool:
        if action.kind != policy.action_kind:
            return False
        if policy.predicate_kind == "tool_name":
            return action.name in policy.tool_names
        return _args_contains(
            action,
            list(policy.needles),
            case_insensitive=policy.case_insensitive,
        )

    def _decide(self, policy: _ReflexPolicy, action: EffectorAction) -> ReflexDecision:
        if policy.effect == "rewrite" and policy.rewrite_content:
            new_args = dict(action.args)
            new_args["content"] = policy.rewrite_content
            return ReflexDecision(
                kind="rewrite",
                policy_id=policy.id,
                reason=policy.deny_reason,
                action=EffectorAction(
                    kind=action.kind,
                    name=action.name,
                    args=new_args,
                    raw=action.raw,
                ),
            )
        return ReflexDecision(
            kind="deny",
            policy_id=policy.id,
            reason=policy.deny_reason,
        )

    def _record(
        self,
        action: EffectorAction,
        decision: ReflexDecision,
        policy: _ReflexPolicy | None,
    ) -> ReflexDecisionRecord:
        return ReflexDecisionRecord(
            turn_id="",
            action_kind=action.kind,
            action_name=action.name,
            decision=decision.kind,
            policy_id=decision.policy_id,
            reason=decision.reason,
            criticality=policy.criticality if policy else None,
        )


__all__ = [
    "EffectorAction",
    "EffectorState",
    "ReflexDecision",
    "ReflexDecisionRecord",
    "ReflexMonitor",
]
