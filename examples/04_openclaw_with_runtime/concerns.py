"""Hand-authored concerns for the OpenClaw + runtime demo (M5 #32).

Two narrow rules:

* **User path** — ``on_user_input`` when the user text mentions ``OpenCOAT``
  (or the older spelling ``COAT``).
* **Memory path** — ``before_memory_write`` on every memory write so the
  joinpoint pipeline produces visible injections when the host fires
  ``agent.memory_write``.
"""

from __future__ import annotations

from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    Pointcut,
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
        pointcut=Pointcut(
            joinpoints=["on_user_input"],
            match=PointcutMatch(any_keywords=["OpenCOAT", "opencoat", "COAT", "coat"]),
        ),
        advice=Advice(
            type=AdviceType.RESPONSE_REQUIREMENT,
            content="Acknowledge the OpenCOAT runtime in one sentence before answering.",
        ),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.PROMPT_LEVEL,
            target="runtime_prompt.output_format",
            priority=0.6,
        ),
    )


def _memory_write_note() -> Concern:
    return Concern(
        id="c-openclaw-memory",
        name="OpenClaw demo — memory write",
        description="Annotate every memory write with a lightweight policy line.",
        pointcut=Pointcut(joinpoints=["before_memory_write"]),
        advice=Advice(
            type=AdviceType.MEMORY_WRITE_GUARD,
            content="Memory writes are mirrored to the DCN when concern_id is set.",
        ),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.MEMORY_LEVEL,
            target="memory_write.policy_note",
            priority=0.5,
        ),
    )


def seed_concerns() -> list[Concern]:
    """Return demo concerns in stable declaration order."""
    return [_user_opencoat_guidance(), _memory_write_note()]


__all__ = ["seed_concerns"]
