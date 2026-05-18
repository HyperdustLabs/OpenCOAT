"""Map runtime event-loop types to well-known lifecycle joinpoint names."""

from __future__ import annotations

# Keys are ``RuntimeEvent.type`` / queued event ``type`` strings.
EVENT_TYPE_TO_JOINPOINT: dict[str, str] = {
    "tool_result": "after_tool_call",
    "feedback": "on_feedback",
    "error": "on_error",
    "env_signal": "on_error",
    "memory_write": "after_memory_write",
}


def joinpoint_name_for_event(event_type: str) -> str | None:
    """Return a catalog joinpoint name for ``event_type``, or ``None`` if unknown."""
    return EVENT_TYPE_TO_JOINPOINT.get(event_type)


__all__ = ["EVENT_TYPE_TO_JOINPOINT", "joinpoint_name_for_event"]
