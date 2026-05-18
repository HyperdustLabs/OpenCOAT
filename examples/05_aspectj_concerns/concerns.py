"""Concerns authored in AspectJ-shaped syntax (ADR-0010).

Legacy ``pointcut`` / ``advice`` / ``weaving_policy`` fields are optional;
the protocol normalizes both styles on load.
"""

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


def shell_guard() -> Concern:
    return Concern(
        id="aspectj-shell-guard",
        name="Block destructive shell (AspectJ syntax)",
        description="Matches user lines mentioning shell; blocks rm -rf on tools.",
        pointcuts=[
            PointcutDef(
                id="pc-user-shell",
                expression='user_message() && args("shell")',
            ),
            PointcutDef(
                id="pc-tool-rm",
                expression='before_tool_call() && args("rm -rf")',
            ),
        ],
        advices=[
            AspectJAdvice(
                id="adv-user",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-user-shell",
                content="Treat shell requests as high-risk; confirm scope before tools.",
                template=AdviceType.RESPONSE_REQUIREMENT,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.OUTPUT_LEVEL,
                    target="runtime_prompt.active_concerns",
                    priority=0.7,
                ),
            ),
            AspectJAdvice(
                id="adv-tool",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-tool-rm",
                content="Refusing destructive shell: rm -rf is blocked.",
                template=AdviceType.TOOL_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.TOOL_LEVEL,
                    target="tool_call.arguments",
                    priority=0.95,
                ),
            ),
        ],
    )


def seed_concerns() -> list[Concern]:
    return [shell_guard()]
