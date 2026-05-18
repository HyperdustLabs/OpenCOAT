"""Tests for :class:`ConcernVerifier`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opencoat_runtime_core.concern.verifier import ConcernVerifier
from opencoat_runtime_protocol import Advice, AdviceType, Concern, ConcernVector
from opencoat_runtime_protocol.envelopes import ActiveConcern


def _concern(
    cid: str = "c-1",
    *,
    advice_type: AdviceType | None = AdviceType.VERIFICATION_RULE,
    content: str = "Cite at least one source.",
    params: dict | None = None,
) -> Concern:
    advice = (
        Advice(type=advice_type, content=content, params=params)
        if advice_type is not None
        else None
    )
    return Concern(id=cid, name=cid, advice=advice)


def _vector(*ids: str) -> ConcernVector:
    return ConcernVector(
        weave_id="t",
        ts=datetime(2026, 5, 8, tzinfo=UTC),
        active_concerns=[ActiveConcern(concern_id=i, activation_score=0.5) for i in ids],
    )


class _StubLLM:
    def __init__(self, reply: str = "yes") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def complete(self, prompt: str, **_: Any) -> str:
        self.calls.append(prompt)
        return self.reply

    def chat(self, *_a: Any, **_k: Any) -> str:
        raise NotImplementedError

    def structured(self, *_a: Any, **_k: Any) -> dict:
        raise NotImplementedError

    def score(self, *_a: Any, **_k: Any) -> float:
        return 0.0


class TestVerifierTurnScoping:
    def test_only_active_concerns_are_verified(self) -> None:
        verifier = ConcernVerifier()
        c1 = _concern("c-1", params={"must_contain": "ok"})
        c2 = _concern("c-2", params={"must_contain": "ok"})
        results = verifier.verify_turn(
            active=_vector("c-1"),
            concerns=[c1, c2],
            host_output="ok",
        )
        assert [r.concern_id for r in results] == ["c-1"]

    def test_concern_without_verification_advice_is_skipped_in_active_view(self) -> None:
        # ``verify_turn`` only enumerates active concerns; ``verify_one``
        # is the one that returns the "no verification advice" verdict.
        verifier = ConcernVerifier()
        c1 = _concern("c-1", advice_type=AdviceType.REASONING_GUIDANCE)
        results = verifier.verify_turn(active=_vector("c-1"), concerns=[c1], host_output="x")
        assert len(results) == 1
        assert results[0].satisfied is False
        assert "no verification" in results[0].notes


class TestVerifierRules:
    def test_regex_match_passes(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"regex": r"\bcite\b"})
        result = verifier.verify_one(c, host_output="please cite this work")
        assert result.satisfied
        assert result.score == 1.0
        assert result.evidence["matched"] is True

    def test_regex_miss_fails(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"regex": r"^never$"})
        result = verifier.verify_one(c, host_output="hello world")
        assert not result.satisfied
        assert result.score == 0.0

    def test_regex_is_case_insensitive_by_default(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"regex": "HELLO"})
        result = verifier.verify_one(c, host_output="hello there")
        assert result.satisfied

    def test_regex_case_sensitive_opt_in(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"regex": "HELLO", "case_sensitive": True})
        result = verifier.verify_one(c, host_output="hello there")
        assert not result.satisfied

    def test_invalid_regex_returns_failure_with_notes(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"regex": "("})
        result = verifier.verify_one(c, host_output="x")
        assert not result.satisfied
        assert "invalid regex" in result.notes

    def test_non_string_regex_param_does_not_crash_pass(self) -> None:
        # Regression: ``advice.params`` is untyped runtime data; a non-string
        # ``regex`` value used to bubble TypeError out of the verifier and
        # take down the whole pass.
        verifier = ConcernVerifier()
        for bad in (None, 42, ["a"], {"x": 1}):
            c = _concern(params={"regex": bad})
            result = verifier.verify_one(c, host_output="x")
            assert not result.satisfied
            assert result.score == 0.0
            assert "invalid regex" in result.notes

    def test_must_contain_accepts_string_or_list(self) -> None:
        verifier = ConcernVerifier()
        single = _concern("a", params={"must_contain": "alpha"})
        many = _concern("b", params={"must_contain": ["alpha", "beta"]})
        assert verifier.verify_one(single, host_output="ALPHA beta").satisfied
        assert verifier.verify_one(many, host_output="alpha beta gamma").satisfied
        assert not verifier.verify_one(many, host_output="alpha only").satisfied

    def test_must_contain_partial_score_reflects_missing_count(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"must_contain": ["alpha", "beta", "gamma"]})
        result = verifier.verify_one(c, host_output="alpha")
        assert not result.satisfied
        # 2 of 3 missing -> score = 1 - 2/3 ≈ 0.333
        assert 0.0 < result.score < 0.5

    def test_must_not_contain_passes_when_absent(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={"must_not_contain": "secret"})
        assert verifier.verify_one(c, host_output="all clear").satisfied
        assert not verifier.verify_one(c, host_output="leak the SECRET now").satisfied

    def test_no_rule_returns_advisory_half_score(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(params={})
        result = verifier.verify_one(c, host_output="x")
        assert not result.satisfied
        assert result.score == 0.5
        assert result.notes == "no rule"


class TestVerifierLLMFallback:
    def test_llm_called_when_use_llm_param_set(self) -> None:
        stub = _StubLLM(reply="yes")
        verifier = ConcernVerifier(llm=stub)
        c = _concern(params={"use_llm": True})
        result = verifier.verify_one(c, host_output="some output")
        assert result.satisfied
        assert result.notes == "llm"
        assert len(stub.calls) == 1
        assert "Cite at least one source." in stub.calls[0]

    def test_llm_no_reply_means_unsatisfied(self) -> None:
        stub = _StubLLM(reply="no")
        verifier = ConcernVerifier(llm=stub)
        c = _concern(params={"use_llm": True})
        result = verifier.verify_one(c, host_output="bad output")
        assert not result.satisfied
        assert result.score == 0.0

    def test_use_llm_without_client_falls_back_to_no_rule(self) -> None:
        verifier = ConcernVerifier()  # no LLM
        c = _concern(params={"use_llm": True})
        result = verifier.verify_one(c, host_output="x")
        assert result.notes == "no rule"

    def test_concern_without_advice_returns_no_verification_advice(self) -> None:
        verifier = ConcernVerifier()
        c = _concern(advice_type=None)
        result = verifier.verify_one(c, host_output="x")
        assert "no verification advice" in result.notes
