"""Export portable in-proc reflex policy specs from the concern store (v0.3 §10.4).

The bridge ``ReflexMonitor`` consumes the JSON returned by
``reflex.policies.export`` so hot-path tool guards can run synchronously
without ``joinpoint.submit`` on every ``before_tool_call``.
"""

from __future__ import annotations

from typing import Any, Literal

from opencoat_runtime_protocol import AdviceType, Concern, LifecycleState, WeavingOperation

ReflexCriticality = Literal["safety_critical", "advisory"]
ActionKind = Literal["tool_call"]

_TOOL_JOINPOINTS = frozenset(
    {
        "before_tool_call",
        "tool.before_call",
    }
)


def _pointcut_keywords(concern: Concern) -> list[str]:
    keys: list[str] = []
    for pc in concern.pointcuts:
        jps = pc.joinpoints or []
        expr = pc.expression or ""
        tool_pc = (
            not jps
            or any(j in _TOOL_JOINPOINTS for j in jps)
            or "before_tool_call" in expr
            or "tool.before_call" in expr
        )
        if not tool_pc:
            continue
        if pc.match and pc.match.any_keywords:
            keys.extend(pc.match.any_keywords)
    if concern.pointcut and concern.pointcut.match and concern.pointcut.match.any_keywords:
        keys.extend(concern.pointcut.match.any_keywords)
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _is_hard_tool_block(concern: Concern) -> tuple[str, list[str]] | None:
    """Return (deny_reason, needles) when concern is a hard tool guard block."""
    for adv in concern.advices:
        template = adv.template or adv.advice_type
        if template != AdviceType.TOOL_GUARD:
            continue
        effect = adv.effect or concern.weaving_policy
        if effect is None:
            continue
        if effect.mode not in {WeavingOperation.BLOCK, WeavingOperation.SUPPRESS, WeavingOperation.ESCALATE}:
            continue
        target = effect.target or ""
        if not (target == "tool_call" or target.startswith("tool_call.")):
            continue
        needles = _pointcut_keywords(concern)
        if not needles:
            continue
        reason = (adv.content or concern.description or f"Blocked by {concern.id}").strip()
        return reason, needles

    if concern.advice and concern.advice.type == AdviceType.TOOL_GUARD:
        wp = concern.weaving_policy
        if wp and wp.mode in {
            WeavingOperation.BLOCK,
            WeavingOperation.SUPPRESS,
            WeavingOperation.ESCALATE,
        }:
            needles = _pointcut_keywords(concern)
            if needles:
                reason = (concern.advice.content or concern.description or f"Blocked by {concern.id}").strip()
                return reason, needles
    return None


def export_reflex_policies(
    concerns: list[Concern],
    *,
    action_kind: ActionKind = "tool_call",
) -> dict[str, Any]:
    """Build portable reflex policy export for the bridge TCB."""
    if action_kind != "tool_call":
        return {"version": "0.1", "policies": []}

    policies: list[dict[str, Any]] = []
    for concern in concerns:
        if concern.lifecycle_state in {LifecycleState.ARCHIVED, LifecycleState.MERGED}:
            continue
        hit = _is_hard_tool_block(concern)
        if hit is None:
            continue
        reason, needles = hit
        criticality: ReflexCriticality = "safety_critical"
        policies.append(
            {
                "id": concern.id,
                "criticality": criticality,
                "action_kind": "tool_call",
                "predicate": {
                    "kind": "args_contains",
                    "needles": needles,
                },
                "deny_reason": reason,
            }
        )

    policies.sort(key=lambda p: p["id"])
    return {"version": "0.1", "policies": policies}


__all__ = ["export_reflex_policies"]
