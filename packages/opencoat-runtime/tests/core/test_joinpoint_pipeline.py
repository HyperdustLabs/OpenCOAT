"""Unit tests for :class:`JoinpointPipeline` (formerly TurnLoop).

These tests pin down the loop's contract:

* Pure pipeline composition (matcher → coordinator → advice → weave).
* Resilience: a misbehaving collaborator must NOT take down the turn.
* Telemetry: the observer sees candidate/activation/injection metrics
  and any escalation logs surfaced by the coordinator.
* Bookkeeping: ``last_vector`` / ``last_injection`` are kept up to date
  for the facade's introspection helpers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from opencoat_runtime_core.advice import AdviceGenerator
from opencoat_runtime_core.config import RuntimeConfig
from opencoat_runtime_core.coordinator import ConcernCoordinator
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.loops import JoinpointPipeline
from opencoat_runtime_core.pointcut.matcher import PointcutMatcher
from opencoat_runtime_core.ports.matcher import MatchResult
from opencoat_runtime_core.weaving import ConcernWeaver
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    JoinpointEvent,
    Pointcut,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class RecordingObserver:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict[str, str]]] = []
        self.logs: list[tuple[str, str, dict[str, Any]]] = []
        self.spans: list[str] = []

    def on_metric(self, name: str, value: float, **labels: str) -> None:
        self.metrics.append((name, value, labels))

    def on_log(self, level: str, message: str, **fields: Any) -> None:
        self.logs.append((level, message, fields))

    def on_span(self, name: str, **attrs: Any):  # type: ignore[no-untyped-def]
        self.spans.append(name)
        return _NullSpan()


class _NullSpan:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *_):  # type: ignore[no-untyped-def]
        return None

    def set_attribute(self, *_):  # type: ignore[no-untyped-def]
        return None


class _ExplodingMatcher:
    def match(self, *_a, **_k) -> MatchResult:  # type: ignore[no-untyped-def]
        raise RuntimeError("matcher boom")


class _AlwaysHitMatcher:
    def __init__(self, score: float = 1.0) -> None:
        self._score = score

    def match(self, *_a, **_k) -> MatchResult:  # type: ignore[no-untyped-def]
        return MatchResult(matched=True, score=self._score, reasons=("test",))


class _ExplodingAdvicePlugin:
    def generate(self, *_a, **_k) -> Advice:  # type: ignore[no-untyped-def]
        raise RuntimeError("advice boom")


class _StaticAdvicePlugin:
    def __init__(self, content: str = "rendered") -> None:
        self._content = content

    def generate(self, concern, _ctx=None) -> Advice:  # type: ignore[no-untyped-def]
        return Advice(type=AdviceType.REASONING_GUIDANCE, content=self._content)


class _DCNAddNodeFails(MemoryDCNStore):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def add_node(self, concern):  # type: ignore[no-untyped-def]
        self.attempts += 1
        raise RuntimeError("dcn add_node boom")


class _DCNLogFails(MemoryDCNStore):
    def __init__(self) -> None:
        super().__init__()
        self.log_attempts = 0

    def log_activation(self, *a, **k):  # type: ignore[no-untyped-def]
        self.log_attempts += 1
        raise RuntimeError("dcn log boom")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concern(
    cid: str,
    *,
    keyword: str | None = "hello",
    advice: Advice | None = None,
) -> Concern:
    pointcut = (
        Pointcut(match=PointcutMatch(any_keywords=[keyword])) if keyword is not None else None
    )
    return Concern(
        id=cid,
        name=f"concern-{cid}",
        description="",
        pointcut=pointcut,
        advice=advice or Advice(type=AdviceType.REASONING_GUIDANCE, content=f"advice-for-{cid}"),
    )


def _joinpoint(text: str = "hello world", *, jp_id: str = "jp-1") -> JoinpointEvent:
    return JoinpointEvent(
        id=jp_id,
        level=1,
        name="before_response",
        host="test",
        ts=datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
        payload={"raw_text": text, "text": text},
    )


def _make_loop(
    *,
    matcher=None,
    advice_plugin=None,
    dcn_store=None,
    observer=None,
    config: RuntimeConfig | None = None,
) -> tuple[JoinpointPipeline, MemoryConcernStore, MemoryDCNStore, RecordingObserver]:
    cfg = config or RuntimeConfig()
    cstore = MemoryConcernStore()
    # ``MemoryDCNStore`` defines ``__len__`` so an empty store is falsy —
    # using ``or`` here would silently swap in a fresh store and lose the
    # caller's instrumentation. Same caution for the recording observer
    # and any future doubles.
    dstore = dcn_store if dcn_store is not None else MemoryDCNStore()
    obs = observer if observer is not None else RecordingObserver()
    loop = JoinpointPipeline(
        config=cfg,
        concern_store=cstore,
        dcn_store=dstore,
        matcher=matcher if matcher is not None else PointcutMatcher(),
        coordinator=ConcernCoordinator(budgets=cfg.budgets),
        weaver=ConcernWeaver(budgets=cfg.budgets),
        advice_plugin=(
            advice_plugin if advice_plugin is not None else AdviceGenerator(llm=StubLLMClient())
        ),
        observer=obs,
    )
    return loop, cstore, dstore, obs


# ---------------------------------------------------------------------------
# Empty / no-op paths
# ---------------------------------------------------------------------------


class TestEmptyStore:
    def test_returns_empty_injection_by_default(self) -> None:
        loop, *_ = _make_loop()
        out = loop.run(_joinpoint())
        assert out is not None
        assert out.injections == []
        assert out.totals.advice_count == 0

    def test_returns_none_when_caller_opts_in(self) -> None:
        loop, *_ = _make_loop()
        out = loop.run(_joinpoint(), return_none_when_empty=True)
        assert out is None
        assert loop.last_vector is None
        assert loop.last_injection is None


class TestConcernsWithoutPointcuts:
    def test_concerns_with_no_pointcut_never_activate(self) -> None:
        # Regression: a Concern without a Pointcut must NOT silently
        # match every joinpoint. The host is opting out of declarative
        # activation; the only valid paths to activation are then the
        # event/heartbeat loops or an explicit upsert with a pointcut.
        loop, cstore, *_ = _make_loop()
        cstore.upsert(_concern("c1", keyword=None))
        out = loop.run(_joinpoint())
        assert out is not None
        assert out.injections == []


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_keyword_match_produces_injection(self) -> None:
        loop, cstore, dstore, _ = _make_loop()
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint("hello there"))
        assert out is not None
        assert [i.concern_id for i in out.injections] == ["c1"]
        # Activation was logged on the DCN.
        assert any(rec["concern_id"] == "c1" for rec in dstore.activation_log())

    def test_multiple_concerns_ranked_in_injection(self) -> None:
        loop, cstore, *_ = _make_loop()
        cstore.upsert(_concern("c1", keyword="hello"))
        cstore.upsert(_concern("c2", keyword="hello"))
        cstore.upsert(_concern("c3", keyword="never-matches"))
        out = loop.run(_joinpoint("hello hello"))
        assert out is not None
        assert {i.concern_id for i in out.injections} == {"c1", "c2"}

    def test_weave_id_minted_from_joinpoint_when_absent(self) -> None:
        loop, cstore, *_ = _make_loop()
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint(jp_id="jp-77"))
        assert out is not None
        assert out.weave_id == "weave-jp-77"

    def test_host_round_id_propagates_to_injection_when_joinpoint_carries_one(self) -> None:
        loop, cstore, *_ = _make_loop()
        cstore.upsert(_concern("c1"))
        jp = JoinpointEvent(
            id="jp-1",
            level=1,
            name="before_response",
            host="test",
            ts=datetime(2026, 5, 8, tzinfo=UTC),
            host_round_id="round-abc",
            payload={"raw_text": "hello"},
        )
        out = loop.run(jp)
        assert out is not None
        assert out.weave_id == "weave-jp-1"
        assert out.host_round_id == "round-abc"

    def test_last_vector_and_last_injection_are_cached(self) -> None:
        loop, cstore, *_ = _make_loop()
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint())
        assert loop.last_injection is out
        assert loop.last_vector is not None
        assert [a.concern_id for a in loop.last_vector.active_concerns] == ["c1"]


# ---------------------------------------------------------------------------
# Resilience — a misbehaving collaborator must not crash the turn
# ---------------------------------------------------------------------------


class TestResilience:
    def test_matcher_exception_skips_concern_and_logs(self) -> None:
        loop, cstore, _, obs = _make_loop(matcher=_ExplodingMatcher())
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint())
        assert out is not None
        assert out.injections == []
        assert any("matcher raised" in msg for _, msg, _ in obs.logs)

    def test_advice_plugin_exception_skips_concern(self) -> None:
        loop, cstore, _, obs = _make_loop(
            matcher=_AlwaysHitMatcher(),
            advice_plugin=_ExplodingAdvicePlugin(),
        )
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint())
        assert out is not None
        # The concern was active but no advice was generated, so the
        # weaver dropped it from the injection. The turn still completes.
        assert out.injections == []
        assert any("advice plugin raised" in msg for _, msg, _ in obs.logs)

    def test_dcn_add_node_failure_does_not_crash_turn(self) -> None:
        dstore = _DCNAddNodeFails()
        loop, cstore, _, obs = _make_loop(
            matcher=_AlwaysHitMatcher(),
            advice_plugin=_StaticAdvicePlugin(),
            dcn_store=dstore,
        )
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint())
        assert out is not None and len(out.injections) == 1
        assert dstore.attempts == 1
        assert any("DCN add_node failed" in msg for _, msg, _ in obs.logs)

    def test_dcn_log_failure_does_not_crash_turn(self) -> None:
        dstore = _DCNLogFails()
        loop, cstore, _, obs = _make_loop(
            matcher=_AlwaysHitMatcher(),
            advice_plugin=_StaticAdvicePlugin(),
            dcn_store=dstore,
        )
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint())
        assert out is not None and len(out.injections) == 1
        assert dstore.log_attempts == 1
        assert any("DCN log_activation failed" in msg for _, msg, _ in obs.logs)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class TestTelemetry:
    def test_observer_sees_candidate_active_and_injection_metrics(self) -> None:
        loop, cstore, _, obs = _make_loop()
        cstore.upsert(_concern("c1"))
        cstore.upsert(_concern("c2"))
        loop.run(_joinpoint("hello hello"))
        names = {m for m, *_ in obs.metrics}
        assert "opencoat.weave.candidates" in names
        assert "opencoat.weave.active_concerns" in names
        assert "opencoat.weave.injection_tokens" in names
        assert "opencoat.weave.injection_advices" in names

    def test_span_opened_per_turn(self) -> None:
        loop, cstore, _, obs = _make_loop()
        cstore.upsert(_concern("c1"))
        loop.run(_joinpoint())
        assert "opencoat.weave" in obs.spans


# ---------------------------------------------------------------------------
# Context propagation
# ---------------------------------------------------------------------------


class TestContext:
    def test_payload_and_extra_context_merged(self) -> None:
        # The matcher receives the merged context; we can't observe the
        # matcher's internals from the public API, so we use an
        # ``_AlwaysHitMatcher`` that records the context it sees.
        seen: list[dict] = []

        class _Recorder:
            def match(self, _pc, _jp, ctx):  # type: ignore[no-untyped-def]
                seen.append(dict(ctx or {}))
                return MatchResult(matched=True, score=1.0)

        loop, cstore, *_ = _make_loop(matcher=_Recorder())
        cstore.upsert(_concern("c1"))
        loop.run(_joinpoint("hello"), context={"user_role": "admin"})
        assert seen, "matcher was not invoked"
        ctx = seen[0]
        assert ctx["raw_text"] == "hello"
        assert ctx["user_role"] == "admin"
        assert ctx["joinpoint"] == "before_response"
        assert ctx["joinpoint_id"] == "jp-1"
        # P2 regression: the minted turn id is always present, even
        # when the joinpoint did not carry one.
        assert ctx["weave_id"] == "weave-jp-1"

    def test_minted_turn_id_propagates_to_context(self) -> None:
        # Regression: when the host omits ``JoinpointEvent.weave_id`` the
        # loop mints ``turn-<jp.id>`` and writes it into
        # ``ConcernInjection.weave_id``. The same value MUST also land in
        # the context every collaborator sees, otherwise matcher /
        # advice / weave logs cannot be correlated with the wire-format
        # turn id (and the docstring of ``_build_context`` would lie).
        seen: list[dict] = []

        class _Recorder:
            def match(self, _pc, _jp, ctx):  # type: ignore[no-untyped-def]
                seen.append(dict(ctx or {}))
                return MatchResult(matched=True, score=1.0)

        loop, cstore, *_ = _make_loop(matcher=_Recorder())
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint(jp_id="jp-99"))
        assert seen and seen[0]["weave_id"] == "weave-jp-99"
        # And it matches the value the weaver stamped on the envelope.
        assert out is not None
        assert out.weave_id == seen[0]["weave_id"]

    def test_host_round_id_in_context_to_context(self) -> None:
        seen: list[dict] = []

        class _Recorder:
            def match(self, _pc, _jp, ctx):  # type: ignore[no-untyped-def]
                seen.append(dict(ctx or {}))
                return MatchResult(matched=True, score=1.0)

        loop, cstore, *_ = _make_loop(matcher=_Recorder())
        cstore.upsert(_concern("c1"))
        jp = JoinpointEvent(
            id="jp-1",
            level=1,
            name="before_response",
            host="test",
            ts=datetime(2026, 5, 8, tzinfo=UTC),
            host_round_id="round-abc",
            payload={"raw_text": "hello"},
        )
        loop.run(jp)
        assert seen and seen[0]["weave_id"] == "weave-jp-1"
        assert seen[0].get("host_round_id") == "round-abc"

    def test_payload_weave_id_does_not_shadow_canonical_turn_id(self) -> None:
        # Regression (Codex PR-5): payload may carry an unrelated ``turn_id``
        # key (or a stale trace id). It must never replace the runtime mint —
        # matcher/advice context must stay aligned with ConcernInjection.weave_id.
        seen: list[dict] = []

        class _Recorder:
            def match(self, _pc, _jp, ctx):  # type: ignore[no-untyped-def]
                seen.append(dict(ctx or {}))
                return MatchResult(matched=True, score=1.0)

        loop, cstore, *_ = _make_loop(matcher=_Recorder())
        cstore.upsert(_concern("c1"))
        jp = JoinpointEvent(
            id="jp-1",
            level=1,
            name="before_response",
            host="test",
            ts=datetime(2026, 5, 8, tzinfo=UTC),
            payload={"raw_text": "hello", "host_round_id": "payload-wrong"},
        )
        out = loop.run(jp)
        assert seen and seen[0]["weave_id"] == "weave-jp-1"
        assert out is not None and out.weave_id == seen[0]["weave_id"]

    def test_explicit_context_weave_id_does_not_shadow_canonical(self) -> None:
        # Same contract as payload: ``context=`` is merged before stamping.
        # Runtime ``turn_id`` always wins so telemetry matches the envelope.
        seen: list[dict] = []

        class _Recorder:
            def match(self, _pc, _jp, ctx):  # type: ignore[no-untyped-def]
                seen.append(dict(ctx or {}))
                return MatchResult(matched=True, score=1.0)

        loop, cstore, *_ = _make_loop(matcher=_Recorder())
        cstore.upsert(_concern("c1"))
        out = loop.run(_joinpoint(), context={"host_round_id": "should-not-win"})
        assert seen and seen[0]["weave_id"] == "weave-jp-1"
        assert out is not None and out.weave_id == seen[0]["weave_id"]

    def test_extra_context_overrides_payload_keys(self) -> None:
        # Same key in both: the explicit ``context`` argument wins. This
        # mirrors the way hosts compose per-turn overrides on top of
        # joinpoint payloads.
        seen: list[dict] = []

        class _Recorder:
            def match(self, _pc, _jp, ctx):  # type: ignore[no-untyped-def]
                seen.append(dict(ctx or {}))
                return MatchResult(matched=True, score=1.0)

        loop, cstore, *_ = _make_loop(matcher=_Recorder())
        cstore.upsert(_concern("c1"))
        loop.run(_joinpoint("hello"), context={"raw_text": "OVERRIDE"})
        assert seen[0]["raw_text"] == "OVERRIDE"


# ---------------------------------------------------------------------------
# Race / freshness scenarios
# ---------------------------------------------------------------------------


class TestRaceConditions:
    def test_active_concern_evicted_between_scan_and_weave_is_skipped(self) -> None:
        # The concern matches at scan time but is gone from the store
        # by the time the loop tries to fetch it for advice generation.
        # Modelled by an advice plugin that deletes the concern from the
        # store when invoked indirectly via a custom store.
        evictions: list[str] = []

        class _EvictOnGet(MemoryConcernStore):
            def get(self, cid):  # type: ignore[no-untyped-def]
                evictions.append(cid)
                return None  # simulate eviction race

        cstore = _EvictOnGet()
        cstore.upsert(_concern("c1"))
        cfg = RuntimeConfig()
        obs = RecordingObserver()
        dstore = MemoryDCNStore()
        loop = JoinpointPipeline(
            config=cfg,
            concern_store=cstore,
            dcn_store=dstore,
            matcher=PointcutMatcher(),
            coordinator=ConcernCoordinator(budgets=cfg.budgets),
            weaver=ConcernWeaver(budgets=cfg.budgets),
            advice_plugin=AdviceGenerator(llm=StubLLMClient()),
            observer=obs,
        )
        out = loop.run(_joinpoint("hello"))
        assert out is not None
        assert out.injections == []
        assert "c1" in evictions
        assert any("vanished from store" in msg for _, msg, _ in obs.logs)
        # P1 regression: even though the coordinator put c1 in the
        # vector, the weaver dropped it (no advice). The DCN MUST NOT
        # see a phantom activation — that would corrupt the ``history``
        # pointcut strategy and (worse) re-add a deleted node.
        assert list(dstore.activation_log()) == []
        assert dstore._nodes == {}

    def test_phantom_activation_not_logged_when_advice_plugin_drops_concern(self) -> None:
        # Same shape as the eviction race but driven by an advice plugin
        # exception. The vector still contains the concern (it was
        # active) but no injection was produced, so the DCN must stay
        # untouched.
        cstore = MemoryConcernStore()
        cstore.upsert(_concern("c1"))
        cfg = RuntimeConfig()
        obs = RecordingObserver()
        dstore = MemoryDCNStore()
        loop = JoinpointPipeline(
            config=cfg,
            concern_store=cstore,
            dcn_store=dstore,
            matcher=_AlwaysHitMatcher(),
            coordinator=ConcernCoordinator(budgets=cfg.budgets),
            weaver=ConcernWeaver(budgets=cfg.budgets),
            advice_plugin=_ExplodingAdvicePlugin(),
            observer=obs,
        )
        out = loop.run(_joinpoint("hello"))
        assert out is not None
        assert out.injections == []
        assert loop.last_vector is not None
        # Coordinator did treat c1 as active …
        assert [a.concern_id for a in loop.last_vector.active_concerns] == ["c1"]
        # … but the DCN must not record an activation for a turn the
        # host never observed.
        assert list(dstore.activation_log()) == []
        assert dstore._nodes == {}

    def test_concern_deleted_after_weaving_but_before_dcn_log_is_skipped(self) -> None:
        # Subtle race: the concern survives advice generation (so it
        # made it into the injection) but is deleted from the store
        # before the DCN logger re-fetches it. We must NOT call
        # ``add_node`` with stale data — that would resurrect the node.
        first_get = {"c1": True}

        class _DeleteAfterAdvice(MemoryConcernStore):
            def get(self, cid):  # type: ignore[no-untyped-def]
                # Allow the first ``get`` (from advice generation) to
                # succeed; the second ``get`` (from _record_activations)
                # sees an empty store.
                if first_get.get(cid):
                    first_get[cid] = False
                    return super().get(cid)
                return None

        cstore = _DeleteAfterAdvice()
        cstore.upsert(_concern("c1"))
        cfg = RuntimeConfig()
        obs = RecordingObserver()
        dstore = MemoryDCNStore()
        loop = JoinpointPipeline(
            config=cfg,
            concern_store=cstore,
            dcn_store=dstore,
            matcher=PointcutMatcher(),
            coordinator=ConcernCoordinator(budgets=cfg.budgets),
            weaver=ConcernWeaver(budgets=cfg.budgets),
            advice_plugin=AdviceGenerator(llm=StubLLMClient()),
            observer=obs,
        )
        out = loop.run(_joinpoint("hello"))
        assert out is not None
        assert [i.concern_id for i in out.injections] == ["c1"]
        # Even though the injection has the concern, the DCN re-fetch
        # found nothing — so nothing is logged and no node is revived.
        assert list(dstore.activation_log()) == []
        assert dstore._nodes == {}
        assert any("vanished from store; activation skipped" in msg for _, msg, _ in obs.logs)


@pytest.mark.parametrize(
    "score",
    [0.0, 0.25, 0.99, 1.0],
)
def test_score_is_propagated_to_active_concern(score: float) -> None:
    loop, cstore, *_ = _make_loop(matcher=_AlwaysHitMatcher(score=score))
    cstore.upsert(_concern("c1"))
    out = loop.run(_joinpoint())
    assert out is not None
    assert loop.last_vector is not None
    active = loop.last_vector.active_concerns[0]
    # PriorityRanker may re-weight, but a score of 0.0 should never go
    # negative and a score of 1.0 should never exceed 1.0.
    assert 0.0 <= active.activation_score <= 1.0
