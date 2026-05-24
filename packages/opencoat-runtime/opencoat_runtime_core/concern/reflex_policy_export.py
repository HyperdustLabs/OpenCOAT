"""Export portable in-proc reflex policy specs from the concern store (v0.3 §10.4).

The bridge ``ReflexMonitor`` consumes the JSON returned by
``reflex.policies.export`` so hot-path guards can run synchronously
without ``joinpoint.submit`` on every hook.
"""

from __future__ import annotations

from typing import Any, Literal

from opencoat_runtime_protocol import (
    AdviceType,
    Concern,
    JoinpointSelector,
    LifecycleState,
    Pointcut,
    PointcutDef,
    WeavingOperation,
)

ReflexCriticality = Literal["safety_critical", "advisory"]
ActionKind = Literal["tool_call", "spawn", "message_out", "queue_enqueue", "all"]

_BLOCK_MODES = frozenset(
    {
        WeavingOperation.BLOCK,
        WeavingOperation.SUPPRESS,
        WeavingOperation.ESCALATE,
    }
)

_TOOL_JOINPOINTS = frozenset({"before_tool_call", "tool.before_call"})
_SPAWN_JOINPOINTS = frozenset(
    {"task.before_create", "subagent_spawning", "subagent.before_spawn"}
)
_MESSAGE_JOINPOINTS = frozenset(
    {
        "before_response",
        "response.before_final",
        "message_sending",
    }
)
_QUEUE_JOINPOINTS = frozenset({"queue.before_enqueue"})

_ACTION_PROFILES: dict[str, tuple[frozenset[str], tuple[str, ...], bool]] = {
    "tool_call": (_TOOL_JOINPOINTS, ("tool_call",), True),
    "spawn": (_SPAWN_JOINPOINTS, ("task", "subagent"), False),
    "message_out": (_MESSAGE_JOINPOINTS, ("runtime_prompt", "response"), False),
    "queue_enqueue": (_QUEUE_JOINPOINTS, ("queue",), False),
}


def _joinpoint_path(jp: str | JoinpointSelector) -> str:
    if isinstance(jp, str):
        return jp
    if jp.path:
        return jp.path
    if jp.name:
        return jp.name
    return ""


def _expression_mentions_joinpoints(expr: str, joinpoints: frozenset[str]) -> bool:
    return any(jp in expr for jp in joinpoints)


def _pointcut_def_matches(pc: PointcutDef, joinpoints: frozenset[str]) -> bool:
    jps = pc.joinpoints or []
    expr = pc.expression or ""
    return (
        not jps
        or any(_joinpoint_path(j) in joinpoints for j in jps)
        or _expression_mentions_joinpoints(expr, joinpoints)
    )


def _legacy_pointcut_matches(pc: Pointcut, joinpoints: frozenset[str]) -> bool:
    jps = pc.joinpoints or []
    return any(_joinpoint_path(j) in joinpoints for j in jps)


def _target_matches(target: str, prefixes: tuple[str, ...]) -> bool:
    return any(target == p or target.startswith(f"{p}.") for p in prefixes)


def _pointcut_keywords(concern: Concern, joinpoints: frozenset[str]) -> list[str]:
    keys: list[str] = []
    for pc in concern.pointcuts:
        if not _pointcut_def_matches(pc, joinpoints):
            continue
        if pc.match and pc.match.any_keywords:
            keys.extend(pc.match.any_keywords)
    if (
        concern.pointcut
        and _legacy_pointcut_matches(concern.pointcut, joinpoints)
        and concern.pointcut.match
        and concern.pointcut.match.any_keywords
    ):
        keys.extend(concern.pointcut.match.any_keywords)
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def _is_hard_block(
    concern: Concern,
    *,
    joinpoints: frozenset[str],
    target_prefixes: tuple[str, ...],
    require_tool_guard: bool,
) -> tuple[str, list[str]] | None:
    """Return (deny_reason, needles) when concern is a hard block for the profile."""
    for adv in concern.advices:
        if require_tool_guard and adv.template != AdviceType.TOOL_GUARD:
            continue
        effect = adv.effect or concern.weaving_policy
        if effect is None or effect.mode not in _BLOCK_MODES:
            continue
        target = effect.target or ""
        if not _target_matches(target, target_prefixes):
            continue
        needles = _pointcut_keywords(concern, joinpoints)
        if not needles:
            continue
        reason = (adv.content or concern.description or f"Blocked by {concern.id}").strip()
        return reason, needles

    if require_tool_guard and concern.advice and concern.advice.type == AdviceType.TOOL_GUARD:
        wp = concern.weaving_policy
        if wp and wp.mode in _BLOCK_MODES:
            needles = _pointcut_keywords(concern, joinpoints)
            if needles:
                reason = (
                    concern.advice.content or concern.description or f"Blocked by {concern.id}"
                ).strip()
                return reason, needles
    return None


def _export_one_kind(concerns: list[Concern], action_kind: ActionKind) -> list[dict[str, Any]]:
    if action_kind == "all":
        return []

    profile = _ACTION_PROFILES.get(action_kind)
    if profile is None:
        return []

    joinpoints, target_prefixes, require_tool_guard = profile
    predicate_kind = "args_contains" if action_kind == "tool_call" else "text_contains"

    policies: list[dict[str, Any]] = []
    for concern in concerns:
        if concern.lifecycle_state in {LifecycleState.ARCHIVED, LifecycleState.MERGED}:
            continue
        hit = _is_hard_block(
            concern,
            joinpoints=joinpoints,
            target_prefixes=target_prefixes,
            require_tool_guard=require_tool_guard,
        )
        if hit is None:
            continue
        reason, needles = hit
        policies.append(
            {
                "id": concern.id,
                "criticality": "safety_critical",
                "action_kind": action_kind,
                "predicate": {
                    "kind": predicate_kind,
                    "needles": needles,
                },
                "deny_reason": reason,
            }
        )
    policies.sort(key=lambda p: p["id"])
    return policies


def export_reflex_policies(
    concerns: list[Concern],
    *,
    action_kind: ActionKind = "tool_call",
) -> dict[str, Any]:
    """Build portable reflex policy export for the bridge TCB."""
    if action_kind == "all":
        merged: list[dict[str, Any]] = []
        for kind in ("tool_call", "spawn", "message_out", "queue_enqueue"):
            merged.extend(_export_one_kind(concerns, kind))
        merged.sort(key=lambda p: (p["action_kind"], p["id"]))
        return {"version": "0.1", "policies": merged}

    return {"version": "0.1", "policies": _export_one_kind(concerns, action_kind)}


__all__ = ["export_reflex_policies"]
