"""Hand-authored concerns for the OpenClaw plugin scaffold (AOP (AspectJ) syntax, ADR-0010)."""

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
from opencoat_runtime_protocol.envelopes import PointcutMatch


def _opencoat_session_start() -> Concern:
    return Concern(
        id="c-openclaw-session-start",
        name="OpenClaw scaffold — session start notice",
        description="Fires on runtime_start (agent.started).",
        pointcuts=[PointcutDef(id="pc-start", expression="runtime_start()")],
        advices=[
            AopAdvice(
                id="adv-start",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-start",
                content="You are running under the OpenCOAT runtime. Be concise.",
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


def _opencoat_memory_note() -> Concern:
    return Concern(
        id="c-openclaw-memory-note",
        name="OpenClaw scaffold — memory write note",
        description="Annotate memory writes with a lightweight policy hint.",
        pointcuts=[PointcutDef(id="pc-mem", expression="before_memory_write()")],
        advices=[
            AopAdvice(
                id="adv-mem",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-mem",
                content="Memory writes are mirrored to the DCN via OpenClawMemoryBridge.",
                template=AdviceType.MEMORY_WRITE_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.MEMORY_LEVEL,
                    target="memory_write.policy_note",
                    priority=0.5,
                ),
            ),
        ],
    )


def _opencoat_user_keyword() -> Concern:
    return Concern(
        id="c-openclaw-user-opencoat",
        name="OpenClaw scaffold — OpenCOAT mention",
        description="Runtime hint when the user mentions OpenCOAT or COAT.",
        pointcuts=[
            PointcutDef(
                id="pc-user",
                expression="on_user_input()",
                joinpoints=["on_user_input"],
                match=PointcutMatch(any_keywords=["OpenCOAT", "opencoat", "COAT", "coat"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-user",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-user",
                content="Acknowledge the OpenCOAT runtime in one sentence before answering.",
                template=AdviceType.REASONING_GUIDANCE,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.PROMPT_LEVEL,
                    target="runtime_prompt.reasoning_guidance",
                    priority=0.6,
                ),
            ),
        ],
    )


def seed_concerns() -> list[Concern]:
    return [_opencoat_session_start(), _opencoat_memory_note(), _opencoat_user_keyword()]


__all__ = ["seed_concerns"]
