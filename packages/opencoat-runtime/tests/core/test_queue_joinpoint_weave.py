"""Queue joinpoint weaving — block and rewrite advice targets."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.advice import AdviceGenerator
from opencoat_runtime_core.config import RuntimeConfig
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.loops import JoinpointPipeline
from opencoat_runtime_core.pointcut.matcher import PointcutMatcher
from opencoat_runtime_core.weaving import ConcernWeaver
from opencoat_runtime_protocol import (
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    JoinpointEvent,
    PointcutDef,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore


def _queue_concern(
    concern_id: str,
    *,
    mode: WeavingOperation,
    target: str,
    keyword: str,
    content: str,
) -> Concern:
    return Concern(
        id=concern_id,
        name=f"queue test {concern_id}",
        pointcuts=[
            PointcutDef(
                id="pc-queue",
                joinpoints=["queue.before_enqueue"],
                match=PointcutMatch(any_keywords=[keyword]),
            )
        ],
        advices=[
            AopAdvice(
                id="adv-queue",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-queue",
                content=content,
                template=AdviceType.MEMORY_WRITE_GUARD
                if mode == WeavingOperation.BLOCK
                else AdviceType.REWRITE_GUIDANCE,
                effect=WeavingPolicy(
                    mode=mode,
                    level=WeavingLevel.OUTPUT_LEVEL,
                    target=target,
                    priority=0.9,
                ),
            )
        ],
    )


def _make_loop() -> tuple[JoinpointPipeline, MemoryConcernStore]:
    cfg = RuntimeConfig()
    store = MemoryConcernStore()
    loop = JoinpointPipeline(
        config=cfg,
        concern_store=store,
        dcn_store=MemoryDCNStore(),
        matcher=PointcutMatcher(),
        coordinator=ConcernCoordinator(budgets=cfg.budgets),
        weaver=ConcernWeaver(budgets=cfg.budgets),
        advice_plugin=AdviceGenerator(llm=StubLLMClient()),
    )
    return loop, store


def _queue_joinpoint(prompt: str) -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-queue-test",
        level=1,
        name="queue.before_enqueue",
        host="openclaw",
        agent_session_id="sess-queue",
        host_round_id="run-queue",
        ts=datetime.now(UTC),
        payload={
            "stage": "before_enqueue",
            "prompt": prompt,
            "summary_line": "user follow-up",
            "text": prompt,
            "raw_text": prompt,
        },
    )


def test_queue_block_advice_woven() -> None:
    loop, store = _make_loop()
    store.upsert(
        _queue_concern(
            "oc.test.queue-block",
            mode=WeavingOperation.BLOCK,
            target="queue.prompt",
            keyword="QUEUE_DOGFOOD_BLOCK",
            content="blocked by test",
        ),
    )

    injection = loop.run(_queue_joinpoint("QUEUE_DOGFOOD_BLOCK enqueue me"))
    assert injection is not None
    assert any(row.mode == "block" and row.target == "queue.prompt" for row in injection.injections)


def test_queue_prompt_rewrite_woven() -> None:
    loop, store = _make_loop()
    store.upsert(
        _queue_concern(
            "oc.test.queue-prompt",
            mode=WeavingOperation.REWRITE,
            target="queue.prompt",
            keyword="QUEUE_DOGFOOD_REWRITE_PROMPT",
            content="rewritten prompt",
        ),
    )

    injection = loop.run(
        _queue_joinpoint("QUEUE_DOGFOOD_REWRITE_PROMPT please queue"),
    )
    assert injection is not None
    assert any(
        row.mode == "rewrite" and row.target == "queue.prompt" and "rewritten prompt" in row.content
        for row in injection.injections
    )


def test_queue_summary_rewrite_woven() -> None:
    loop, store = _make_loop()
    store.upsert(
        _queue_concern(
            "oc.test.queue-summary",
            mode=WeavingOperation.REWRITE,
            target="queue.summary_line",
            keyword="QUEUE_DOGFOOD_REWRITE_SUMMARY",
            content="rewritten summary",
        ),
    )

    injection = loop.run(
        _queue_joinpoint("QUEUE_DOGFOOD_REWRITE_SUMMARY tweak"),
    )
    assert injection is not None
    assert any(
        row.mode == "rewrite" and row.target == "queue.summary_line" for row in injection.injections
    )
