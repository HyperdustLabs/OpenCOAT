"""Tests for portable reflex policy export (bridge TCB sync)."""

from __future__ import annotations

from opencoat_runtime_core.concern.reflex_policy_export import export_reflex_policies
from opencoat_runtime_protocol import (
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    PointcutDef,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch


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


def test_export_demo_tool_block() -> None:
    out = export_reflex_policies([_demo_tool_block()])
    assert out["version"] == "0.1"
    assert len(out["policies"]) == 1
    row = out["policies"][0]
    assert row["id"] == "demo-tool-block"
    assert row["predicate"]["kind"] == "args_contains"
    assert "rm -rf" in row["predicate"]["needles"]


def test_skips_untemplated_aop_advice() -> None:
    concern = Concern(
        id="untemplated-guard",
        name="bad row",
        pointcuts=[
            PointcutDef(
                id="pc-tool",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["rm -rf"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="a1",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-tool",
                content="would block",
                template=None,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.TOOL_LEVEL,
                    target="tool_call.arguments",
                ),
            ),
        ],
    )
    out = export_reflex_policies([concern])
    assert out["policies"] == []


def test_skips_soft_advice() -> None:
    soft = Concern(
        id="soft-hint",
        name="hint",
        advices=[
            AopAdvice(
                id="a1",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc",
                content="be careful",
                template=AdviceType.REASONING_GUIDANCE,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.PROMPT_LEVEL,
                    target="runtime_prompt.output_format",
                ),
            ),
        ],
        pointcuts=[PointcutDef(id="pc", expression="before_tool_call()")],
    )
    out = export_reflex_policies([soft])
    assert out["policies"] == []


def test_export_queue_block_concern() -> None:
    concern = Concern(
        id="oc.dogfood.queue-block",
        name="queue block",
        pointcuts=[
            PointcutDef(
                id="pc-queue-block",
                joinpoints=["queue.before_enqueue"],
                match=PointcutMatch(any_keywords=["QUEUE_DOGFOOD_BLOCK"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-block",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-queue-block",
                content="Follow-up queue blocked.",
                template=AdviceType.MEMORY_WRITE_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.MEMORY_LEVEL,
                    target="queue.prompt",
                ),
            ),
        ],
    )
    out = export_reflex_policies([concern], action_kind="queue_enqueue")
    assert len(out["policies"]) == 1
    row = out["policies"][0]
    assert row["action_kind"] == "queue_enqueue"
    assert row["predicate"]["kind"] == "text_contains"
    assert "QUEUE_DOGFOOD_BLOCK" in row["predicate"]["needles"]


def test_export_all_merges_kinds() -> None:
    queue = Concern(
        id="oc.dogfood.queue-block",
        name="queue block",
        pointcuts=[
            PointcutDef(
                id="pc-queue-block",
                joinpoints=["queue.before_enqueue"],
                match=PointcutMatch(any_keywords=["QUEUE_DOGFOOD_BLOCK"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-block",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-queue-block",
                content="blocked",
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.MEMORY_LEVEL,
                    target="queue.prompt",
                ),
            ),
        ],
    )
    out = export_reflex_policies([_demo_tool_block(), queue], action_kind="all")
    kinds = {p["action_kind"] for p in out["policies"]}
    assert kinds == {"tool_call", "queue_enqueue"}


def test_export_memory_block_concern() -> None:
    concern = Concern(
        id="mem-secret-block",
        name="block secrets in session JSONL",
        pointcuts=[
            PointcutDef(
                id="pc-mem",
                joinpoints=["memory.before_write"],
                match=PointcutMatch(any_keywords=["TOP_SECRET"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-block",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-mem",
                content="Secrets must not be persisted.",
                template=AdviceType.MEMORY_WRITE_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.MEMORY_LEVEL,
                    target="memory_write.content",
                ),
            ),
        ],
    )
    out = export_reflex_policies([concern], action_kind="memory_write")
    assert len(out["policies"]) == 1
    row = out["policies"][0]
    assert row["action_kind"] == "memory_write"
    assert row.get("effect", "deny") == "deny"


def test_export_message_rewrite_concern() -> None:
    concern = Concern(
        id="msg-leak-repair",
        name="repair outbound leaks",
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
                content="[OpenCOAT repaired outbound]",
                template=AdviceType.REWRITE_GUIDANCE,
                effect=WeavingPolicy(
                    mode=WeavingOperation.REWRITE,
                    level=WeavingLevel.PROMPT_LEVEL,
                    target="runtime_prompt.output",
                ),
            ),
        ],
    )
    out = export_reflex_policies([concern], action_kind="message_out")
    assert len(out["policies"]) == 1
    row = out["policies"][0]
    assert row["effect"] == "rewrite"
    assert row["rewrite_content"] == "[OpenCOAT repaired outbound]"
