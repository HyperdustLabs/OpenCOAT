"""Runtime JP automation — tick/event weave and prompt-surface expansion."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.config import JoinpointAutomation
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.runtime import RuntimeEvent
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    JoinpointEvent,
    Pointcut,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _runtime(*, automation: JoinpointAutomation | None = None) -> OpenCOATRuntime:
    auto = automation or JoinpointAutomation()
    return OpenCOATRuntime(
        RuntimeConfig(joinpoint_automation=auto),
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )


def _concern_runtime_tick(keyword: str) -> Concern:
    return Concern(
        id="tick-guard",
        name="tick-guard",
        description=keyword,
        pointcut=Pointcut(
            joinpoints=["runtime_tick"],
            match=PointcutMatch(any_keywords=[keyword]),
        ),
        advice=Advice(type=AdviceType.REASONING_GUIDANCE, content="tick advice"),
    )


def _concern_user_message(keyword: str) -> Concern:
    return Concern(
        id="msg-guard",
        name="msg-guard",
        description=keyword,
        pointcut=Pointcut(
            joinpoints=["user_message"],
            match=PointcutMatch(any_keywords=[keyword]),
        ),
        advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="msg advice"),
    )


class TestTickAutomation:
    def test_tick_weaves_runtime_tick_joinpoint(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern_runtime_tick("candidate"))
        rt.tick(datetime(2026, 5, 15, tzinfo=UTC))
        inj = rt.last_injection()
        assert inj is not None
        assert inj.weave_id.startswith("weave-tick-")
        assert any(row.concern_id == "tick-guard" for row in inj.injections)

    def test_tick_disabled_skips_weave(self) -> None:
        rt = _runtime(automation=JoinpointAutomation(weave_on_tick=False))
        rt.concern_store.upsert(_concern_runtime_tick("candidate"))
        rt.tick(datetime(2026, 5, 15, tzinfo=UTC))
        assert rt.last_injection() is None


class TestEventAutomation:
    def test_tick_drains_and_weaves_mapped_events(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(
            Concern(
                id="after-tool",
                name="after-tool",
                description="tool",
                pointcut=Pointcut(joinpoints=["after_tool_call"]),
                advice=Advice(type=AdviceType.TOOL_GUARD, content="checked"),
            )
        )
        rt.on_event(
            RuntimeEvent(
                type="tool_result",
                ts=datetime(2026, 5, 15, tzinfo=UTC),
                payload={"raw_text": "done"},
            )
        )
        assert rt.snapshot().pending_event_count == 1
        rt.tick(datetime(2026, 5, 15, 12, 1, tzinfo=UTC))
        assert rt.snapshot().pending_event_count == 0
        inj = rt.last_injection()
        assert inj is not None
        assert any(row.concern_id == "after-tool" for row in inj.injections)


class TestPromptSurfaceExpansion:
    def test_messages_expand_to_user_message_joinpoint(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(_concern_user_message("shell"))
        jp = JoinpointEvent(
            id="jp-surface",
            level=1,
            name="before_response",
            host="test",
            ts=datetime(2026, 5, 15, tzinfo=UTC),
            payload={"messages": [{"role": "user", "content": "use shell"}]},
        )
        inj = rt.on_joinpoint(jp)
        assert inj is not None
        assert inj.weave_id == "weave-jp-surface"
        assert any(row.concern_id == "msg-guard" for row in inj.injections)
