"""Tests for OpenClaw v0.1 joinpoint aliases (ADR-0011)."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.joinpoint import (
    JOINPOINT_CATALOG,
    OPENCLAW_V01_MVP_JOINPOINTS,
    canonical_joinpoint_name,
    joinpoint_names_match,
)
from opencoat_runtime_core.joinpoint.model import JoinpointEvent
from opencoat_runtime_core.pointcut import PointcutMatcher
from opencoat_runtime_protocol import Pointcut, PointcutMatch


def test_mvp_joinpoints_in_catalog() -> None:
    for name in OPENCLAW_V01_MVP_JOINPOINTS:
        assert name in JOINPOINT_CATALOG, name


def test_canonical_joinpoint_name_resolves_aliases() -> None:
    assert canonical_joinpoint_name("tool.before_call") == "before_tool_call"
    assert canonical_joinpoint_name("input.received") == "on_user_input"
    assert canonical_joinpoint_name("before_tool_call") == "before_tool_call"


def test_joinpoint_names_match_across_legacy_and_v01() -> None:
    assert joinpoint_names_match("tool.before_call", "before_tool_call")
    assert joinpoint_names_match("input.received", "on_user_input")
    assert not joinpoint_names_match("before_tool_call", "before_response")


def test_matcher_accepts_v01_pointcut_against_legacy_event_name() -> None:
    matcher = PointcutMatcher()
    jp = JoinpointEvent(
        id="jp-1",
        level=1,
        name="before_tool_call",
        host="openclaw",
        ts=datetime(2026, 5, 19, tzinfo=UTC),
        payload={"text": "rm -rf", "raw_text": "rm -rf"},
    )
    pc = Pointcut(
        joinpoints=["tool.before_call"],
        match=PointcutMatch(any_keywords=["rm"]),
    )
    result = matcher.match(pc, jp)
    assert result.matched


def test_queue_joinpoint_in_catalog_not_emitted_by_bridge_yet() -> None:
    assert "queue.before_enqueue" in JOINPOINT_CATALOG
    assert canonical_joinpoint_name("queue.before_enqueue") == "queue.before_enqueue"
