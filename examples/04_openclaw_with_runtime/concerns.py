"""OpenClaw + runtime demo concerns (AOP (AspectJ) syntax, ADR-0010)."""

from __future__ import annotations

from opencoat_runtime_protocol import (
    AdviceKind,
    AdviceType,
    AspectJAdvice,
    Concern,
    PointcutDef,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch


def _user_opencoat_guidance() -> Concern:
    return Concern(
        id="c-openclaw-user",
        name="OpenClaw demo — OpenCOAT mention",
        description="When the user asks about OpenCOAT (or COAT), add a short runtime hint.",
        pointcuts=[
            PointcutDef(
                id="pc-user",
                expression="on_user_input()",
                joinpoints=["on_user_input"],
                match=PointcutMatch(any_keywords=["OpenCOAT", "opencoat", "COAT", "coat"]),
            ),
        ],
        advices=[
            AspectJAdvice(
                id="adv-user",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-user",
                content="Acknowledge the OpenCOAT runtime in one sentence before answering.",
                template=AdviceType.RESPONSE_REQUIREMENT,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.PROMPT_LEVEL,
                    target="runtime_prompt.output_format",
                    priority=0.6,
                ),
            ),
        ],
    )


def _memory_write_note() -> Concern:
    return Concern(
        id="c-openclaw-memory",
        name="OpenClaw demo — memory write",
        description="Annotate every memory write with a lightweight policy line.",
        pointcuts=[PointcutDef(id="pc-mem", expression="before_memory_write()")],
        advices=[
            AspectJAdvice(
                id="adv-mem",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-mem",
                content="Memory writes are mirrored to the DCN when concern_id is set.",
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


def seed_concerns() -> list[Concern]:
    return [_user_opencoat_guidance(), _memory_write_note()]


__all__ = ["seed_concerns"]
