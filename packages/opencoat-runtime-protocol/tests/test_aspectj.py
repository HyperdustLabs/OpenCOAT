"""AOP (AspectJ) concern syntax and normalization."""

from __future__ import annotations

from opencoat_runtime_protocol import (
    Advice,
    AdviceKind,
    AdviceType,
    AspectJAdvice,
    Concern,
    Pointcut,
    PointcutDef,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.aspectj import (
    parse_pointcut_expression,
    pointcut_def_to_pointcut,
    primary_pointcut,
    sync_concern_aspectj,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch


def test_parse_pointcut_expression_joinpoint_and_args() -> None:
    jps, match = parse_pointcut_expression('user_message() && args("rm -rf")')
    assert jps == ["user_message"]
    assert match is not None
    assert match.any_keywords == ["rm -rf"]


def test_legacy_concern_gains_aspectj_lists() -> None:
    c = Concern(
        id="c-legacy",
        name="shell guard",
        pointcut=Pointcut(
            joinpoints=["before_tool_call"],
            match=PointcutMatch(any_keywords=["rm -rf"]),
        ),
        advice=Advice(
            type=AdviceType.TOOL_GUARD,
            content="block destructive shell",
        ),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.BLOCK,
            level=WeavingLevel.TOOL_LEVEL,
            target="tool_call.arguments",
            priority=0.9,
        ),
    )
    assert len(c.pointcuts) == 1
    assert c.pointcuts[0].id == "pc-default"
    assert len(c.advices) == 1
    assert c.advices[0].kind == AdviceKind.BEFORE
    assert c.advices[0].template == AdviceType.TOOL_GUARD


def test_aspectj_lists_materialize_legacy_pointcut() -> None:
    c = Concern(
        id="c-aj",
        name="user line guard",
        pointcuts=[
            PointcutDef(
                id="pc-user",
                expression='user_message() && args("shell")',
            )
        ],
        advices=[
            AspectJAdvice(
                id="adv-1",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-user",
                content="check shell usage",
                template=AdviceType.RESPONSE_REQUIREMENT,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.OUTPUT_LEVEL,
                    priority=0.8,
                ),
            )
        ],
    )
    pc = primary_pointcut(c)
    assert pc is not None
    assert "user_message" in pc.joinpoints
    assert pc.match is not None
    assert "shell" in (pc.match.any_keywords or [])


def test_sync_idempotent() -> None:
    c = Concern(
        id="c-sync",
        name="x",
        pointcut=Pointcut(joinpoints=["runtime_start"]),
        advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="hi"),
    )
    once = sync_concern_aspectj(c)
    twice = sync_concern_aspectj(once)
    assert once.pointcut == twice.pointcut
    assert len(once.pointcuts) == len(twice.pointcuts)


def test_pointcut_def_to_pointcut_prefers_structured_joinpoints() -> None:
    defn = PointcutDef(
        expression="before_response()",
        joinpoints=["user_message"],
        match=PointcutMatch(any_keywords=["secret"]),
    )
    pc = pointcut_def_to_pointcut(defn)
    assert pc.joinpoints == ["user_message"]
    assert pc.match is not None
    assert pc.match.any_keywords == ["secret"]
