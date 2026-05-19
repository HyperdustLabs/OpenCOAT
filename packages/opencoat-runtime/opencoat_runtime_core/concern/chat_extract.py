"""Derive NL text from user-input joinpoints for ``concern.extract``."""

from __future__ import annotations

from opencoat_runtime_protocol import JoinpointEvent

from ..pointcut._text import extract_text

# Joinpoint names that carry end-user chat the extractor should mine.
USER_INPUT_JOINPOINT_NAMES: frozenset[str] = frozenset(
    {
        "on_user_input",
        "user_message",
    }
)


def chat_text_for_extraction(jp: JoinpointEvent, *, max_user_messages: int = 3) -> str | None:
    """Return user chat text from a joinpoint payload, or ``None`` if unsuitable."""
    if jp.name not in USER_INPUT_JOINPOINT_NAMES:
        return None

    payload = jp.payload or {}
    messages = payload.get("messages")
    if isinstance(messages, list):
        user_lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                user_lines.append(content.strip())
        if user_lines:
            tail = user_lines[-max_user_messages:]
            return "\n\n".join(tail)

    text = extract_text(jp).strip()
    return text or None


__all__ = ["USER_INPUT_JOINPOINT_NAMES", "chat_text_for_extraction"]
