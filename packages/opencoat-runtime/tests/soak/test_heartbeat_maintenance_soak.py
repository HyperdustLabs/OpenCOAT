"""Short heartbeat maintenance soak (M6 PR4 harness)."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_daemon.runtime_builder import build_heartbeat_maintenance
from opencoat_runtime_protocol import (
    ActivationState,
    Advice,
    AdviceType,
    Concern,
    LifecycleState,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _concern(cid: str, *, keywords: list[str], score: float = 0.6) -> Concern:
    return Concern(
        id=cid,
        name=cid,
        description=cid,
        lifecycle_state=LifecycleState.ACTIVE.value,
        activation_state=ActivationState(score=score, decay=0.0, active=True),
        pointcut=Pointcut(
            joinpoints=["before_response"],
            match=PointcutMatch(any_keywords=keywords),
        ),
        advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="x"),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.OUTPUT_LEVEL,
            target="response.body",
            priority=0.5,
        ),
    )


def test_heartbeat_maintenance_soak_ten_ticks() -> None:
    """Run ten maintenance ticks without error — stand-in for 24h daemon soak."""
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    store.upsert(_concern("a", keywords=["NVDA", "周三", "收盘"]))
    store.upsert(_concern("b", keywords=["NVDA", "周三", "分析"], score=0.2))
    rt = OpenCOATRuntime(
        concern_store=store,
        dcn_store=dcn,
        llm=StubLLMClient(),
        heartbeat_maintenance=build_heartbeat_maintenance(store, dcn),
    )
    ts = datetime(2026, 5, 19, tzinfo=UTC)
    for _ in range(10):
        report = rt.tick(ts)
        assert report.candidate_count >= 1
        assert report.decay_count >= 0
