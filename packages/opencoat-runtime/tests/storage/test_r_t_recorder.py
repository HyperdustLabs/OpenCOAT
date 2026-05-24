"""Tests for r_t JSONL recorder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_storage.jsonl.r_t_recorder import RtJsonlRecorder


def test_append_rt_record(tmp_path: Path) -> None:
    path = tmp_path / "r_t.jsonl"
    rec = RtRecord(
        ts=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        session_id="s1",
        turn_id="run-1",
        joinpoint="after_tool_call",
        hook="after_tool_call",
        signal=RtSignal(kind="tool_outcome", tool_name="shell.exec"),
        r=1.0,
    )
    with RtJsonlRecorder(path) as writer:
        writer.append(rec)
        assert writer.count == 1
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "r_t"
    assert row["signal"]["tool_name"] == "shell.exec"
