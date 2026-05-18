"""Three "dramatic" demo concerns loaded by ``opencoat concern import --demo``.

Authored in AOP (AspectJ) syntax (ADR-0010); legacy fields are filled on load.
"""

from __future__ import annotations

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

DEMO_PROMPT_PREFIX_ID = "demo-prompt-prefix"
DEMO_TOOL_BLOCK_ID = "demo-tool-block"
DEMO_MEMORY_TAG_ID = "demo-memory-tag"


def _demo_prompt_prefix() -> Concern:
    return Concern(
        id=DEMO_PROMPT_PREFIX_ID,
        name="Demo — runtime banner in system prompt",
        description=(
            "Inserts a small marker so you can confirm at a glance "
            "that OpenCOAT-managed concerns reached the system prompt."
        ),
        pointcuts=[PointcutDef(id="pc-runtime", expression="runtime_start()")],
        advices=[
            AopAdvice(
                id="adv-banner",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-runtime",
                content="Begin every response with `[OpenCOAT demo active]`.",
                template=AdviceType.RESPONSE_REQUIREMENT,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.PROMPT_LEVEL,
                    target="runtime_prompt.active_concerns",
                    priority=0.5,
                ),
            ),
        ],
    )


def _demo_tool_block() -> Concern:
    return Concern(
        id=DEMO_TOOL_BLOCK_ID,
        name="Demo — block destructive shell commands",
        description=(
            "Refuses any tool call whose arguments mention ``rm -rf``. "
            "Demonstrates BLOCK weaving on ``tool_call.arguments``."
        ),
        pointcuts=[
            PointcutDef(
                id="pc-tool",
                expression='before_tool_call() && args("rm -rf")',
                joinpoints=["before_tool_call"],
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-block",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-tool",
                content="Refusing destructive shell command — `rm -rf` is blocked by demo-tool-block.",
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


def _demo_memory_tag() -> Concern:
    return Concern(
        id=DEMO_MEMORY_TAG_ID,
        name="Demo — annotate every memory write",
        description="Annotate memory writes; pairs with OpenClawMemoryBridge DCN mirroring.",
        pointcuts=[PointcutDef(id="pc-mem", expression="before_memory_write()")],
        advices=[
            AopAdvice(
                id="adv-mem",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-mem",
                content="memory.policy=demo-memory-tag: write annotated by demo concern.",
                template=AdviceType.MEMORY_WRITE_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.ANNOTATE,
                    level=WeavingLevel.MEMORY_LEVEL,
                    target="memory_write.policy_note",
                    priority=0.4,
                ),
            ),
        ],
    )


def demo_concerns() -> list[Concern]:
    """Return the canonical three-concern demo set in stable order."""
    return [_demo_prompt_prefix(), _demo_tool_block(), _demo_memory_tag()]


__all__ = [
    "DEMO_MEMORY_TAG_ID",
    "DEMO_PROMPT_PREFIX_ID",
    "DEMO_TOOL_BLOCK_ID",
    "demo_concerns",
]
