"""Tests for EffectorKernel.run_turn (v0.3 §3.5)."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.advice import AdviceGenerator
from opencoat_runtime_core.config import RuntimeConfig
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_core.effector import EffectorAction, EffectorKernel
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


def _demo_tool_block() -> Concern:
    return Concern(
        id="demo-tool-block",
        name="Demo — block destructive shell commands",
        pointcuts=[
            PointcutDef(
                id="pc-tool",
                expression="before_tool_call()",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["rm -rf", "rm  -rf"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-block",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-tool",
                content="Refusing destructive shell command.",
                template=AdviceType.TOOL_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.TOOL_LEVEL,
                    target="tool_call.arguments",
                    priority=0.9,
                ),
            ),
        ],
    )


def _make_kernel(store: MemoryConcernStore) -> EffectorKernel:
    cfg = RuntimeConfig()
    dcn = MemoryDCNStore()
    pipeline = JoinpointPipeline(
        config=cfg,
        concern_store=store,
        dcn_store=dcn,
        matcher=PointcutMatcher(),
        coordinator=ConcernCoordinator(budgets=cfg.budgets),
        weaver=ConcernWeaver(budgets=cfg.budgets),
        advice_plugin=AdviceGenerator(llm=StubLLMClient()),
    )
    return EffectorKernel(pipeline=pipeline, concern_store=store)


def test_run_turn_denies_destructive_tool() -> None:
    store = MemoryConcernStore()
    store.upsert(_demo_tool_block())
    kernel = _make_kernel(store)
    jp = JoinpointEvent(
        id="jp-1",
        level=3,
        name="before_tool_call",
        host="test",
        ts=datetime.now(tz=UTC),
        payload={"toolName": "shell.exec"},
    )
    action = EffectorAction(
        kind="tool_call",
        name="shell.exec",
        args={"command": "rm -rf /tmp/x"},
    )
    outcome = kernel.run_turn(jp, action, turn_id="run-1")
    assert outcome.allowed is False
    assert outcome.decision == "deny"
    assert outcome.policy_id == "demo-tool-block"
    assert outcome.record.signal.kind == "tool_blocked"


def test_run_turn_allows_benign_tool() -> None:
    store = MemoryConcernStore()
    store.upsert(_demo_tool_block())
    kernel = _make_kernel(store)
    jp = JoinpointEvent(
        id="jp-2",
        level=3,
        name="before_tool_call",
        host="test",
        ts=datetime.now(tz=UTC),
    )
    action = EffectorAction(
        kind="tool_call",
        name="shell.exec",
        args={"command": "ls -la"},
    )
    outcome = kernel.run_turn(jp, action, turn_id="run-2")
    assert outcome.allowed is True
    assert outcome.decision == "allow"
    assert outcome.record.signal.kind == "tool_outcome"


def test_run_turn_verify_repair_rewrites_message() -> None:
    store = MemoryConcernStore()
    store.upsert(
        Concern(
            id="msg-repair",
            name="repair leaks",
            pointcuts=[
                PointcutDef(
                    id="pc-msg",
                    joinpoints=["response.before_final"],
                    match=PointcutMatch(any_keywords=["LEAK_ME"]),
                ),
            ],
            advices=[
                AopAdvice(
                    id="adv-rewrite",
                    kind=AdviceKind.BEFORE,
                    pointcut_ref="pc-msg",
                    content="[repaired]",
                    effect=WeavingPolicy(
                        mode=WeavingOperation.REWRITE,
                        level=WeavingLevel.PROMPT_LEVEL,
                        target="runtime_prompt.output",
                    ),
                ),
            ],
        )
    )
    kernel = _make_kernel(store)
    jp = JoinpointEvent(
        id="jp-3",
        level=3,
        name="message_sending",
        host="test",
        ts=datetime.now(tz=UTC),
    )
    action = EffectorAction(
        kind="message_out",
        name="message_out",
        args={"content": "please LEAK_ME"},
    )
    outcome = kernel.run_turn(jp, action, turn_id="run-3")
    assert outcome.allowed is True
    assert outcome.decision == "rewrite"
    assert outcome.action.args["content"] == "[repaired]"
    assert outcome.repair_attempts == 1
