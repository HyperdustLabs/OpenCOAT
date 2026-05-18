"""Tests for :class:`ConcernWeaver`."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.config import RuntimeBudgets
from opencoat_runtime_core.weaving import ConcernWeaver
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    ConcernVector,
    WeavingLevel,
    WeavingOperation,
)
from opencoat_runtime_protocol.envelopes import ActiveConcern, WeavingPolicy


def _vector(*active: ActiveConcern) -> ConcernVector:
    return ConcernVector(
        weave_id="t",
        agent_session_id="sess-1",
        ts=datetime(2026, 5, 8, tzinfo=UTC),
        active_concerns=list(active),
    )


def _concern(cid: str, *, policy: WeavingPolicy | None = None) -> Concern:
    return Concern(id=cid, name=cid, weaving_policy=policy)


def _advice(
    cid: str = "c-1",
    *,
    text: str = "hello",
    advice_type: AdviceType = AdviceType.REASONING_GUIDANCE,
    max_tokens: int | None = None,
) -> Advice:
    return Advice(type=advice_type, content=text, max_tokens=max_tokens)


def _active(cid: str, *, score: float = 0.5, priority: float | None = None) -> ActiveConcern:
    return ActiveConcern(concern_id=cid, activation_score=score, priority=priority)


class TestConcernWeaverDefaults:
    def test_uses_advice_type_defaults_when_policy_unset(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        vector = _vector(_active("c-1"))
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={"c-1": _concern("c-1")},
            advices={"c-1": _advice(text="be careful")},
        )
        assert len(out.injections) == 1
        inj = out.injections[0]
        assert inj.target == "runtime_prompt.reasoning_guidance"
        assert inj.mode == WeavingOperation.INSERT
        assert inj.level == WeavingLevel.PROMPT_LEVEL
        assert inj.advice_type == AdviceType.REASONING_GUIDANCE
        assert inj.content == "be careful"

    def test_policy_overrides_target_mode_and_level(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        policy = WeavingPolicy(
            mode=WeavingOperation.WARN,
            level=WeavingLevel.SPAN_LEVEL,
            target="user_message.span:risky",
        )
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1", policy=policy)},
            advices={"c-1": _advice()},
        )
        inj = out.injections[0]
        assert inj.target == "user_message.span:risky"
        assert inj.mode == WeavingOperation.WARN
        assert inj.level == WeavingLevel.SPAN_LEVEL

    def test_tool_guard_advice_defaults_to_block_and_tool_level(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1")},
            advices={"c-1": _advice(advice_type=AdviceType.TOOL_GUARD, text="no PII")},
        )
        inj = out.injections[0]
        assert inj.mode == WeavingOperation.BLOCK
        assert inj.level == WeavingLevel.TOOL_LEVEL


class TestConcernWeaverOrdering:
    def test_sorted_by_priority_then_concern_id(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        vector = _vector(
            _active("c-low", priority=0.1),
            _active("c-high", priority=0.9),
            _active("c-mid", priority=0.5),
        )
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={cid: _concern(cid) for cid in ["c-low", "c-high", "c-mid"]},
            advices={cid: _advice(cid) for cid in ["c-low", "c-high", "c-mid"]},
        )
        assert [i.concern_id for i in out.injections] == ["c-high", "c-mid", "c-low"]

    def test_vector_order_breaks_score_and_priority_ties(self) -> None:
        # When activation_score and weaving priority both tie the weaver
        # falls back to the coordinator's emitted order (= the vector's
        # index). This preserves the coordinator's own tiebreakers
        # (concern_id ascending, per PR-3) instead of re-sorting them.
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        vector = _vector(
            _active("c-a", priority=0.5),
            _active("c-b", priority=0.5),
        )
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={cid: _concern(cid) for cid in ["c-a", "c-b"]},
            advices={cid: _advice(cid) for cid in ["c-a", "c-b"]},
        )
        assert [i.concern_id for i in out.injections] == ["c-a", "c-b"]

    def test_preserves_coordinator_ranking_when_policy_priority_unset(self) -> None:
        # Regression for the post-PR-4 review finding: previously the
        # weaver sorted purely by ``inj.priority``, defaulting missing
        # values to 0.0. Two concerns ranked by the coordinator (different
        # activation_scores) but lacking ``weaving_policy.priority`` would
        # tie and re-order by concern_id, breaking the cutoff under
        # ``max_injection_tokens``. The coordinator's activation_score
        # must be the primary sort signal.
        weaver = ConcernWeaver(budgets=RuntimeBudgets(max_active_concerns=10))
        # ``c-z`` was top-ranked by the coordinator (score 0.9) but its
        # id sorts last; ``c-a`` was bottom-ranked (score 0.1).
        vector = _vector(
            _active("c-z", score=0.9),
            _active("c-a", score=0.1),
        )
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={cid: _concern(cid) for cid in ["c-z", "c-a"]},
            advices={cid: _advice(cid) for cid in ["c-z", "c-a"]},
        )
        assert [i.concern_id for i in out.injections] == ["c-z", "c-a"]

    def test_coordinator_top_concern_survives_token_cutoff(self) -> None:
        # Same scenario as above but pushed through the budget cutoff:
        # if the sort lost the activation_score signal, ``c-z`` (the
        # coordinator's #1) would lose to ``c-a`` and get dropped.
        # Token math (~4 chars/token): "x"*32 -> ~8 tokens. Budget=10
        # admits the first injection, the second pushes us past 10.
        budgets = RuntimeBudgets(max_active_concerns=10, max_injection_tokens=10)
        weaver = ConcernWeaver(budgets=budgets)
        vector = _vector(
            _active("c-z", score=0.9),
            _active("c-a", score=0.1),
        )
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={cid: _concern(cid) for cid in ["c-z", "c-a"]},
            advices={
                "c-z": _advice("c-z", text="x" * 32),
                "c-a": _advice("c-a", text="x" * 32),
            },
        )
        assert [i.concern_id for i in out.injections] == ["c-z"]

    def test_explicit_policy_priority_breaks_activation_score_tie(self) -> None:
        # When the coordinator returns identical activation_scores the
        # weaver should fall back to ``weaving_policy.priority`` for
        # ordering — that's the field's stated purpose.
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        vector = _vector(
            _active("c-low-pri", score=0.5, priority=0.1),
            _active("c-high-pri", score=0.5, priority=0.9),
        )
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={cid: _concern(cid) for cid in ["c-low-pri", "c-high-pri"]},
            advices={cid: _advice(cid) for cid in ["c-low-pri", "c-high-pri"]},
        )
        assert [i.concern_id for i in out.injections] == ["c-high-pri", "c-low-pri"]

    def test_skips_active_concerns_missing_from_advice_or_concern_map(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        vector = _vector(_active("c-1"), _active("c-2"))
        out = weaver.build(
            weave_id="t",
            vector=vector,
            concerns={"c-1": _concern("c-1")},  # c-2 missing
            advices={"c-1": _advice("c-1")},
        )
        assert [i.concern_id for i in out.injections] == ["c-1"]


class TestConcernWeaverTruncation:
    def test_advice_truncated_to_policy_max_tokens(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        policy = WeavingPolicy(max_tokens=2)  # ~8 chars budget
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1", policy=policy)},
            advices={"c-1": _advice(text="x" * 200)},
        )
        inj = out.injections[0]
        assert len(inj.content) <= 9  # 8 chars + ellipsis
        assert inj.content.endswith("…")

    def test_advice_max_tokens_overrides_policy_max_when_smaller(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        policy = WeavingPolicy(max_tokens=200)
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1", policy=policy)},
            advices={"c-1": _advice(text="x" * 200, max_tokens=2)},
        )
        assert len(out.injections[0].content) <= 9

    def test_short_content_passes_through_unchanged(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1")},
            advices={"c-1": _advice(text="hi")},
        )
        assert out.injections[0].content == "hi"


class TestConcernWeaverBudget:
    def test_token_budget_is_a_cutoff_not_binpack(self) -> None:
        # Mirrors the BudgetController contract added in PR-3:
        # once a higher-priority injection cannot fit, smaller lower-
        # priority ones must NOT be promoted into its slot.
        budgets = RuntimeBudgets(max_active_concerns=10, max_injection_tokens=20)
        weaver = ConcernWeaver(budgets=budgets)
        vector = _vector(
            _active("c-high", priority=0.9),
            _active("c-mid", priority=0.5),
            _active("c-low", priority=0.1),
        )
        concerns = {cid: _concern(cid) for cid in ["c-high", "c-mid", "c-low"]}
        advices = {
            "c-high": _advice("c-high", text="x" * 32),  # ~8 tokens
            "c-mid": _advice("c-mid", text="x" * 200),  # truncated to 50; exceeds remainder
            "c-low": _advice("c-low", text="x" * 16),  # ~4 tokens — fits but must not slip past
        }
        out = weaver.build(weave_id="t", vector=vector, concerns=concerns, advices=advices)
        assert [i.concern_id for i in out.injections] == ["c-high"]

    def test_first_oversized_injection_is_always_kept(self) -> None:
        budgets = RuntimeBudgets(max_active_concerns=10, max_injection_tokens=2)
        weaver = ConcernWeaver(budgets=budgets)
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1")},
            advices={"c-1": _advice(text="x" * 100)},
        )
        assert len(out.injections) == 1

    def test_max_active_concerns_caps_distinct_concerns(self) -> None:
        budgets = RuntimeBudgets(max_active_concerns=2, max_injection_tokens=10_000)
        weaver = ConcernWeaver(budgets=budgets)
        vector = _vector(*[_active(f"c-{i}", priority=1.0 - 0.1 * i) for i in range(5)])
        concerns = {f"c-{i}": _concern(f"c-{i}") for i in range(5)}
        advices = {f"c-{i}": _advice(f"c-{i}") for i in range(5)}
        out = weaver.build(weave_id="t", vector=vector, concerns=concerns, advices=advices)
        assert {i.concern_id for i in out.injections} == {"c-0", "c-1"}

    def test_totals_track_tokens_and_counts(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        out = weaver.build(
            weave_id="t",
            vector=_vector(_active("c-1"), _active("c-2")),
            concerns={"c-1": _concern("c-1"), "c-2": _concern("c-2")},
            advices={"c-1": _advice(text="abcd"), "c-2": _advice(text="efgh")},
        )
        assert out.totals is not None
        assert out.totals.advice_count == 2
        assert out.totals.concern_count == 2
        assert out.totals.tokens >= 2  # 1 token per advice minimum


class TestConcernWeaverEnvelope:
    def test_carries_turn_and_session_ids_from_vector(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        out = weaver.build(
            weave_id="turn-99",
            vector=_vector(_active("c-1")),
            concerns={"c-1": _concern("c-1")},
            advices={"c-1": _advice()},
        )
        assert out.weave_id == "turn-99"
        assert out.agent_session_id == "sess-1"
        assert out.ts is not None and out.ts.tzinfo is not None

    def test_empty_vector_produces_empty_injection_with_zero_totals(self) -> None:
        weaver = ConcernWeaver(budgets=RuntimeBudgets())
        out = weaver.build(
            weave_id="t",
            vector=_vector(),
            concerns={},
            advices={},
        )
        assert out.injections == []
        assert out.totals is not None
        assert out.totals.tokens == 0
        assert out.totals.concern_count == 0
        assert out.totals.advice_count == 0
