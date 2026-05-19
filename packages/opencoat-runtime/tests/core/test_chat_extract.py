"""Tests for chat_text_for_extraction."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.concern.chat_extract import chat_text_for_extraction
from opencoat_runtime_protocol import JoinpointEvent

_TS = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


def test_on_user_input_single_message() -> None:
    jp = JoinpointEvent.model_validate(
        {
            "id": "jp-1",
            "level": 1,
            "name": "on_user_input",
            "host": "openclaw",
            "ts": _TS.isoformat(),
            "payload": {
                "messages": [{"role": "user", "content": "Analyze NVDA until Wednesday close."}],
            },
        }
    )
    assert chat_text_for_extraction(jp) == "Analyze NVDA until Wednesday close."


def test_user_message_uses_last_user_lines() -> None:
    jp = JoinpointEvent.model_validate(
        {
            "id": "jp-2",
            "level": 2,
            "name": "user_message",
            "host": "openclaw",
            "ts": _TS.isoformat(),
            "payload": {
                "messages": [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "ok"},
                    {"role": "user", "content": "second question"},
                ],
            },
        }
    )
    assert chat_text_for_extraction(jp) == "first\n\nsecond question"


def test_non_user_joinpoint_returns_none() -> None:
    jp = JoinpointEvent.model_validate(
        {
            "id": "jp-3",
            "level": 1,
            "name": "before_tool_call",
            "host": "openclaw",
            "ts": _TS.isoformat(),
            "payload": {"text": "rm -rf"},
        }
    )
    assert chat_text_for_extraction(jp) is None
