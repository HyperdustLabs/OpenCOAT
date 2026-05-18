"""P3 batch surface weave and P4 span / adviceexecution discovery."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.config import JoinpointAutomation
from opencoat_runtime_core.joinpoint.discovery import JoinpointDiscovery
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    JoinpointEvent,
    JoinpointSelector,
    Pointcut,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _runtime(*, automation: JoinpointAutomation | None = None) -> OpenCOATRuntime:
    return OpenCOATRuntime(
        RuntimeConfig(joinpoint_automation=automation or JoinpointAutomation()),
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )


def _root_with_messages() -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-root-p34",
        level=1,
        name="before_response",
        host="test",
        ts=datetime(2026, 5, 18, tzinfo=UTC),
        payload={
            "messages": [
                {"role": "user", "content": "Never run rm -rf in shell."},
            ]
        },
    )


class TestP4SpanDiscovery:
    def test_discover_span_joinpoints(self) -> None:
        root = _root_with_messages()
        discovered = JoinpointDiscovery(
            automation=JoinpointAutomation(discover_spans=True, discover_tokens=False)
        ).expand(root)
        names = {jp.name for jp in discovered}
        assert "semantic_span" in names
        span = next(jp for jp in discovered if jp.name == "semantic_span")
        assert span.level == 4
        assert "imperative" in (span.payload or {}).get("semantic_type", "")


class TestP3BatchSurface:
    def test_span_level_pointcut_batch_weave(self) -> None:
        rt = _runtime()
        rt.concern_store.upsert(
            Concern(
                id="span-guard",
                name="span-guard",
                pointcut=Pointcut(
                    joinpoints=[JoinpointSelector(level="span", match=["rm"])],
                ),
                advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="no rm"),
            )
        )
        inj = rt.on_joinpoint(_root_with_messages())
        assert inj is not None
        assert any(row.concern_id == "span-guard" for row in inj.injections)
        assert inj.weave_id == "weave-jp-root-p34"

    def test_adviceexecution_emits_for_meta_pointcut(self) -> None:
        auto = JoinpointAutomation(emit_adviceexecution=True, discover_spans=False)
        rt = _runtime(automation=auto)
        rt.concern_store.upsert(
            Concern(
                id="user-guard",
                name="user-guard",
                pointcut=Pointcut(
                    joinpoints=["user_message"],
                    match=PointcutMatch(any_keywords=["shell"]),
                ),
                advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="careful"),
            )
        )
        rt.concern_store.upsert(
            Concern(
                id="meta-ae",
                name="meta-ae",
                pointcut=Pointcut(joinpoints=["adviceexecution"]),
                advice=Advice(type=AdviceType.ESCALATION_NOTICE, content="audit"),
            )
        )
        inj = rt.on_joinpoint(_root_with_messages())
        assert inj is not None
        assert any(row.concern_id == "meta-ae" for row in inj.injections)
