"""Tests for credit.r_t JSON-RPC methods."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_daemon.ipc.jsonrpc_dispatch import JsonRpcHandler
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _req(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": req_id,
    }


def test_credit_rt_append_and_stats(monkeypatch, tmp_path) -> None:
    from opencoat_runtime_cli.demo_concerns import demo_concerns

    store = MemoryConcernStore()
    for c in demo_concerns():
        store.upsert(c)
    rt = OpenCOATRuntime(
        concern_store=store,
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )
    log = tmp_path / "r_t.jsonl"
    svc = RtPlasticityService(concern_store=store, dcn_store=rt.dcn_store, path=log)
    h = JsonRpcHandler(rt, rt_service=svc)
    record = RtRecord(
        ts=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
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
    out = h.handle(_req("credit.r_t.append", {"record": record.model_dump(mode="json")}))
    assert "error" not in out
    assert out["result"]["ok"] is True
    assert out["result"]["plasticity"]["reinforced"] == 1

    stats = h.handle(_req("credit.r_t.stats"))
    assert stats["result"]["count"] == 1
