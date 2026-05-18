"""Tests for :class:`JoinpointDiscovery`."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.joinpoint.discovery import JoinpointDiscovery
from opencoat_runtime_core.joinpoint.levels import JoinpointLevel
from opencoat_runtime_core.loops.heartbeat_loop import HeartbeatReport
from opencoat_runtime_protocol import JoinpointEvent


def _parent() -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-root",
        level=1,
        name="before_response",
        host="test",
        host_round_id="run-1",
        ts=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
        payload={
            "messages": [
                {"role": "user", "content": "shell rm -rf"},
                {
                    "role": "system",
                    "content": "rules",
                    "sections": [{"path": "runtime_prompt.rules", "raw_text": "no rm"}],
                },
            ]
        },
    )


def test_expand_discovers_message_and_section_joinpoints() -> None:
    expanded = JoinpointDiscovery(max_discovered=32).expand(_parent())
    names = [jp.name for jp in expanded]
    assert names[0] == "before_response"
    assert "user_message" in names
    assert "system_message" in names
    assert "runtime_prompt.rules" in names
    child = next(jp for jp in expanded if jp.name == "user_message")
    assert child.id == "jp-root#msg:0"
    assert child.level == int(JoinpointLevel.MESSAGE)
    assert child.host_round_id == "run-1"


def test_runtime_tick_joinpoint_shape() -> None:
    report = HeartbeatReport(ts=datetime(2026, 5, 15, tzinfo=UTC), candidate_count=3)
    jp = JoinpointDiscovery().runtime_tick_joinpoint(report)
    assert jp.name == "runtime_tick"
    assert jp.level == int(JoinpointLevel.RUNTIME)
    assert jp.payload["candidate_count"] == 3


def test_joinpoint_from_event_maps_tool_result() -> None:
    jp = JoinpointDiscovery().joinpoint_from_event(
        {
            "type": "tool_result",
            "ts": "2026-05-15T12:00:00+00:00",
            "payload": {"raw_text": "ok", "host_round_id": "run-9"},
        }
    )
    assert jp is not None
    assert jp.name == "after_tool_call"
    assert jp.host_round_id == "run-9"
