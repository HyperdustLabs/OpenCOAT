"""OpenClaw v0.1 joinpoint aliases (dotted names → canonical catalog names).

See docs/design/opencoat-openclaw-joinpoint-model-v0.1.md and ADR-0011.
"""

from __future__ import annotations

# Dotted v0.1 name → canonical name in JOINPOINT_CATALOG (legacy flat preferred).
OPENCLAW_V01_ALIASES: dict[str, str] = {
    # Runtime
    "runtime.start": "runtime_start",
    "runtime.shutdown": "runtime_stop",
    "runtime.tick": "runtime_tick",
    "runtime.error": "runtime_error",
    "runtime.recovery": "runtime_recovery",
    # Input
    "input.received": "on_user_input",
    # Reasoning / planning
    "reasoning.before_start": "before_reasoning",
    "reasoning.after_start": "after_reasoning",
    "planning.before_start": "before_planning",
    "planning.after_start": "after_planning",
    "planning.plan_updated": "after_planning",
    "command.output_stream": "command.output_stream",
    "patch.summary_created": "patch.summary_created",
    # Tool
    "tool.before_call": "before_tool_call",
    "tool.after_execute": "after_tool_call",
    "tool.result.received": "after_tool_call",
    # Prompt / response
    "prompt.before_build": "before_response",
    "prompt.before_send_to_model": "before_response",
    "response.after_final": "after_response",
    "response.before_final": "before_response",
    # Memory
    "memory.before_write": "before_memory_write",
    "memory.after_write": "after_memory_write",
    # Error / heartbeat / feedback
    "error.detected": "on_error",
    "heartbeat.before_run": "on_heartbeat",
    "feedback.received": "on_feedback",
    "concern.after_reinforce": "adviceexecution",
    # Prompt sections (1:1 with catalog paths)
    "prompt.system.role_definition": "system_prompt.role_definition",
    "prompt.system.rules": "system_prompt.rules",
    "prompt.developer.constraints": "developer_prompt.task_constraints",
    "prompt.user.original_request": "user_prompt.original_request",
    "prompt.runtime.active_concerns": "runtime_prompt.active_concerns",
    "prompt.runtime.tool_instructions": "runtime_prompt.tool_instructions",
    "prompt.runtime.output_format": "runtime_prompt.output_format",
    "prompt.runtime.verification_rules": "runtime_prompt.verification_rules",
}

# MVP integration wave (docs/design/opencoat-openclaw-joinpoint-model-v0.1.md §4).
OPENCLAW_V01_MVP_JOINPOINTS: frozenset[str] = frozenset(
    {
        "input.received",
        "queue.before_enqueue",
        "queue.after_enqueue",
        "queue.before_collect",
        "reply_run.before_begin",
        "reply_run.phase.running",
        "prompt.before_send_to_model",
        "planning.plan_updated",
        "tool.before_call",
        "tool.result.received",
        "approval.requested",
        "task.before_create",
        "task.after_create",
        "task.before_terminal",
        "response.before_final",
        "verification.after_fail",
        "heartbeat.before_run",
        "error.detected",
    }
)


def canonical_joinpoint_name(name: str) -> str:
    """Resolve a pointcut or event joinpoint name to its canonical catalog name."""
    return OPENCLAW_V01_ALIASES.get(name, name)


def joinpoint_names_match(pointcut_name: str, event_name: str) -> bool:
    """True when two joinpoint names refer to the same catalog joinpoint."""
    return canonical_joinpoint_name(pointcut_name) == canonical_joinpoint_name(event_name)


__all__ = [
    "OPENCLAW_V01_ALIASES",
    "OPENCLAW_V01_MVP_JOINPOINTS",
    "canonical_joinpoint_name",
    "joinpoint_names_match",
]
