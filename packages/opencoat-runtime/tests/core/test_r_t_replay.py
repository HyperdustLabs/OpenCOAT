"""Deterministic r_t JSONL replay harness tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_core.credit.rt_replay import read_rt_jsonl, replay_rt_jsonl
from opencoat_runtime_protocol import Concern
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _write_jsonl(path: Path, records: list[RtRecord]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.model_dump(mode="json")) + "\n")


def test_replay_is_deterministic(tmp_path: Path) -> None:
    records = [
        RtRecord(
            ts=datetime(2026, 5, 24, tzinfo=UTC),
            session_id="s1",
            turn_id="run-1",
            joinpoint="before_tool_call",
            hook="before_tool_call",
            signal=RtSignal(
                kind="tool_blocked",
                reflex={"policy_id": "demo-tool-block", "decision": "deny"},
            ),
            r=1.0,
        ),
        RtRecord(
            ts=datetime(2026, 5, 24, 1, tzinfo=UTC),
            session_id="s1",
            turn_id="run-1",
            joinpoint="after_tool_call",
            hook="after_tool_call",
            signal=RtSignal(
                kind="tool_outcome",
                tool_name="shell.exec",
                reflex={"policy_id": "demo-tool-block", "decision": "deny"},
            ),
            r=1.0,
        ),
    ]
    path = tmp_path / "r_t.jsonl"
    _write_jsonl(path, records)
    assert len(read_rt_jsonl(path)) == 2

    def run_once() -> dict[str, float]:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(Concern(id="demo-tool-block", name="block"))
        return replay_rt_jsonl(
            path,
            concern_store=store,
            dcn_store=dcn,
            engine=PlasticityEngine(step_delta=0.1),
        )

    first = run_once()
    second = run_once()
    assert first == second
    assert first["demo-tool-block"] > 0.0
