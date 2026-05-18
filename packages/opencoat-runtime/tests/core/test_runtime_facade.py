"""End-to-end tests for :class:`OpenCOATRuntime`.

These pin the *external* contract of the facade: a host that wires the
in-memory stores + stub LLM can drive the three loop entrypoints and
inspect runtime state without touching any internal collaborator.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.runtime import RuntimeEvent, RuntimeSnapshot
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    JoinpointEvent,
    Pointcut,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _runtime() -> OpenCOATRuntime:
    return OpenCOATRuntime(
        RuntimeConfig(),
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )


def _concern(
    cid: str,
    *,
    keyword: str,
    advice_type: AdviceType = AdviceType.REASONING_GUIDANCE,
    target: str | None = None,
) -> Concern:
    return Concern(
        id=cid,
        name=f"concern-{cid}",
        description=f"keyword={keyword}",
        pointcut=Pointcut(match=PointcutMatch(any_keywords=[keyword])),
        advice=Advice(type=advice_type, content=f"advice for {cid}"),
        weaving_policy=WeavingPolicy(target=target) if target else None,
    )


def _joinpoint(text: str) -> JoinpointEvent:
    return JoinpointEvent(
        id=f"jp-{abs(hash(text)) % 10000}",
        level=1,
        name="before_response",
        host="test",
        ts=datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
        payload={"raw_text": text, "text": text},
    )


# ---------------------------------------------------------------------------
# Turn loop
# ---------------------------------------------------------------------------


class TestOnJoinpoint:
    def test_no_concerns_returns_empty_injection(self) -> None:
        rt = _runtime()
        out = rt.on_joinpoint(_joinpoint("hello"))
        assert out is not None and out.injections == []

    def test_matching_concern_appears_in_injection(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern("c1", keyword="cite"))
        out = rt.on_joinpoint(_joinpoint("please cite the source"))
        assert out is not None
        assert [i.concern_id for i in out.injections] == ["c1"]

    def test_current_vector_reflects_latest_turn(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern("c1", keyword="hello"))
        rt.on_joinpoint(_joinpoint("hello"))
        vec = rt.current_vector()
        assert vec is not None
        assert [a.concern_id for a in vec.active_concerns] == ["c1"]

    def test_last_injection_reflects_latest_turn(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern("c1", keyword="hello"))
        out = rt.on_joinpoint(_joinpoint("hello"))
        assert rt.last_injection() is out

    def test_no_match_leaves_current_vector_pointing_to_empty(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern("c1", keyword="never"))
        rt.on_joinpoint(_joinpoint("hello"))
        vec = rt.current_vector()
        assert vec is not None
        assert vec.active_concerns == []


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------


class TestOnEvent:
    def test_dispatched_event_is_queued(self) -> None:
        rt = _runtime()
        rt.on_event(
            RuntimeEvent(
                type="tool_result",
                ts=datetime(2026, 5, 8, tzinfo=UTC),
                payload={"tool": "search", "ok": True},
            )
        )
        drained = rt.drain_events()
        assert len(drained) == 1
        assert drained[0]["type"] == "tool_result"

    def test_subscriber_is_invoked_synchronously(self) -> None:
        rt = _runtime()
        seen: list[dict] = []
        rt.subscribe(seen.append)
        rt.on_event(
            RuntimeEvent(
                type="env",
                ts=datetime(2026, 5, 8, tzinfo=UTC),
                payload={"k": 1},
            )
        )
        assert seen and seen[0]["type"] == "env"

    def test_subscriber_exception_does_not_break_dispatch(self) -> None:
        rt = _runtime()

        def boom(_: dict) -> None:
            raise RuntimeError("nope")

        rt.subscribe(boom)
        # Must not raise; the event is still queued.
        rt.on_event(RuntimeEvent(type="x", ts=datetime(2026, 5, 8, tzinfo=UTC), payload={}))
        assert len(rt.drain_events()) == 1

    def test_queued_event_is_isolated_from_post_dispatch_payload_mutation(self) -> None:
        rt = _runtime()
        payload: dict = {"nested": {"x": 1}}
        rt.on_event(
            RuntimeEvent(
                type="t",
                ts=datetime(2026, 5, 8, tzinfo=UTC),
                payload=payload,
            )
        )
        payload["nested"]["x"] = 999
        drained = rt.drain_events()
        assert drained[0]["payload"]["nested"]["x"] == 1

    def test_subscriber_payload_mutation_does_not_alter_queued_event(self) -> None:
        rt = _runtime()

        def mutator(ev: dict) -> None:
            ev["payload"]["k"] = 999

        rt.subscribe(mutator)
        rt.on_event(
            RuntimeEvent(
                type="t",
                ts=datetime(2026, 5, 8, tzinfo=UTC),
                payload={"k": 0},
            )
        )
        drained = rt.drain_events()
        assert drained[0]["payload"]["k"] == 0


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------


class TestTick:
    def test_returns_report_with_inventory(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern("c1", keyword="x"))
        rt.concern_store.upsert(_concern("c2", keyword="y"))
        report = rt.tick(datetime(2026, 5, 8, tzinfo=UTC))
        assert report.candidate_count == 2
        # M1 is no-op for actual maintenance.
        assert report.decay_count == 0
        assert report.merge_count == 0


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_counts_concerns_and_dcn_after_turn(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern("c1", keyword="hello"))
        rt.on_joinpoint(_joinpoint("hello world"))
        snap = rt.snapshot()
        assert isinstance(snap, RuntimeSnapshot)
        assert snap.concern_count == 1
        assert snap.active_concern_count == 1
        # The DCN was written by the joinpoint pipeline's activation logger.
        assert snap.dcn_node_count >= 1
        assert snap.pending_event_count == 0

    def test_snapshot_pending_events_reflects_unflushed_queue(self) -> None:
        rt = _runtime()
        rt.on_event(RuntimeEvent(type="x", ts=datetime(2026, 5, 8, tzinfo=UTC), payload={}))
        snap = rt.snapshot()
        assert snap.pending_event_count == 1
