"""Integration test: append r_t then consume reweight."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_protocol import Concern
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def test_append_and_consume_reinforces_concern(tmp_path: Path) -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(Concern(id="demo-tool-block", name="block"))
    log = tmp_path / "r_t.jsonl"
    svc = RtPlasticityService(concern_store=store, dcn_store=dcn, path=log)
    svc.append(
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
            r=0.0,
        )
    )
    stats = svc.consume()
    assert stats.reinforced == 1
    updated = store.get("demo-tool-block")
    assert updated is not None
    assert updated.lifecycle_state == "reinforced"
