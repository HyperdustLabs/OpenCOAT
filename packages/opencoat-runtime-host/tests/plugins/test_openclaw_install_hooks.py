"""Tests for :func:`install_hooks` + :class:`InstalledHooks` (M5 #31).

Coverage divides into two halves:

* The original M5 #31 surface — subscription bookkeeping, runtime
  dispatch, memory-bridge side-channel, uninstall idempotency. These
  pin the wiring :func:`install_hooks` set up at land.
* The pickup API (this PR) — the half of M5 that was missing:
  capturing the runtime's :class:`ConcernInjection` into
  :attr:`InstalledHooks.pending` and surfacing it via
  :meth:`InstalledHooks.apply_to` /
  :meth:`InstalledHooks.guard_tool_call`. The end-to-end test seeds a
  real ``OpenCOATRuntime`` with the OpenClaw scaffold's demo concerns
  and asserts that firing an event mutates the host context in a way
  the user can see with the naked eye — i.e. closes the
  event → concern → injection → host-state loop the demo flow needs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_host_openclaw import (
    InstalledHooks,
    OpenClawAdapter,
    OpenClawEventName,
    OpenClawHost,
    OpenClawMemoryBridge,
    PendingInjection,
    install_hooks,
)
from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    ConcernInjection,
    Injection,
    JoinpointEvent,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeHost:
    """Records subscribe / unsubscribe calls + replays events."""

    subscriptions: dict[str, list[Callable[[dict[str, Any]], None]]] = field(default_factory=dict)
    unsubscribe_count: int = 0

    def subscribe(
        self,
        event_name: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        self.subscriptions.setdefault(event_name, []).append(callback)

        def _unsubscribe() -> None:
            self.unsubscribe_count += 1
            self.subscriptions[event_name].remove(callback)

        return _unsubscribe

    def fire(self, event_name: str, payload: dict[str, Any]) -> None:
        for cb in list(self.subscriptions.get(event_name, [])):
            cb(payload)


def _build_runtime() -> OpenCOATRuntime:
    return OpenCOATRuntime(
        RuntimeConfig(),
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )


def _seed_concern(runtime: OpenCOATRuntime, concern_id: str, *, name: str = "stub") -> None:
    """Add a minimal concern node so ``log_activation`` doesn't reject."""
    runtime.dcn_store.add_node(
        Concern(
            id=concern_id,
            name=name,
            pointcut=Pointcut(),
        )
    )


# ---------------------------------------------------------------------------
# OpenClawHost protocol shape
# ---------------------------------------------------------------------------


class TestOpenClawHostProtocol:
    def test_fake_host_is_recognised_as_openclaw_host(self) -> None:
        assert isinstance(FakeHost(), OpenClawHost)

    def test_plain_object_is_not_an_openclaw_host(self) -> None:
        assert not isinstance(object(), OpenClawHost)


# ---------------------------------------------------------------------------
# install_hooks — subscription bookkeeping
# ---------------------------------------------------------------------------


class TestInstallSubscriptions:
    def test_subscribes_every_known_event_name_by_default(self) -> None:
        host = FakeHost()
        installed = install_hooks(host, runtime=_build_runtime())
        assert set(host.subscriptions.keys()) == {name.value for name in OpenClawEventName}
        assert installed.is_installed is True

    def test_event_names_argument_overrides_default(self) -> None:
        host = FakeHost()
        install_hooks(
            host,
            runtime=_build_runtime(),
            event_names=("agent.user_message", "agent.before_tool"),
        )
        assert set(host.subscriptions.keys()) == {
            "agent.user_message",
            "agent.before_tool",
        }

    def test_installed_hooks_returns_adapter_runtime_bridge(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        adapter = OpenClawAdapter()
        bridge = OpenClawMemoryBridge(dcn_store=runtime.dcn_store)
        installed = install_hooks(
            host,
            runtime=runtime,
            adapter=adapter,
            bridge=bridge,
        )
        assert isinstance(installed, InstalledHooks)
        assert installed.host is host
        assert installed.runtime is runtime
        assert installed.adapter is adapter
        assert installed.bridge is bridge

    def test_default_adapter_is_constructed_when_omitted(self) -> None:
        host = FakeHost()
        installed = install_hooks(host, runtime=_build_runtime())
        assert isinstance(installed.adapter, OpenClawAdapter)
        assert installed.bridge is None


# ---------------------------------------------------------------------------
# install_hooks — runtime dispatch
# ---------------------------------------------------------------------------


class TestRuntimeDispatch:
    def test_user_message_routes_through_runtime(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(host, runtime=runtime)

        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {"text": "hi"}})

        # Snapshot bumps pending_event_count? No — on_joinpoint is the
        # joinpoint pipeline, not the event loop. We rely on the fact that an
        # active turn has a last-vector (possibly None when no concerns
        # matched, but the call should not raise).
        snapshot = runtime.snapshot()
        assert snapshot is not None  # contract sanity

    def test_unknown_event_name_is_swallowed_silently(self) -> None:
        """Subscribing to a custom event name routes through the adapter
        too — the adapter returns ``None`` for unknown joinpoints and
        the callback drops it without raising."""
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(
            host,
            runtime=runtime,
            event_names=("agent.custom_x",),
        )
        host.fire("agent.custom_x", {"host_round_id": "t-1", "payload": {}})

    def test_callback_injects_event_name_when_payload_omits_it(self) -> None:
        """Real OpenClaw delivers the payload *without* echoing the
        event name. The wrapper must inject it so the adapter's typed
        validator doesn't reject the dict."""
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(host, runtime=runtime)
        # No event_name in payload — must not raise.
        host.fire("agent.user_message", {"host_round_id": "t-1"})

    def test_invalid_envelope_field_propagates_validation_error(self) -> None:
        """Type-invalid envelope fields (``ts`` not a datetime, etc.)
        surface as ``ValidationError`` so misconfigured hosts fail
        loudly. Unknown fields are tolerated by being routed to
        ``payload`` — see ``_to_envelope`` for the coercion rules."""
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(host, runtime=runtime)
        with pytest.raises(ValidationError):
            host.fire(
                "agent.user_message",
                # ``ts`` must parse as a datetime — bool is not coercible.
                {"host_round_id": "t-1", "ts": True},
            )

    def test_unknown_flat_fields_are_tucked_under_payload(self) -> None:
        """Real OpenClaw subscribers receive the event body directly
        (e.g. ``{"text": "hi"}`` for ``agent.user_message``). The
        callback splits envelope fields out and wraps the rest under
        ``payload`` so the adapter validation succeeds."""
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(host, runtime=runtime)
        host.fire(
            "agent.user_message",
            {"host_round_id": "t-1", "text": "hello"},
        )

    def test_envelope_shaped_payload_is_accepted_as_is(self) -> None:
        """When the host already emits ``{weave_id, payload: {...}}``
        the callback only fills in ``event_name`` and leaves the
        envelope intact."""
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(host, runtime=runtime)
        host.fire(
            "agent.user_message",
            {"host_round_id": "t-1", "payload": {"text": "hi"}},
        )


# ---------------------------------------------------------------------------
# install_hooks — memory bridge side-channel
# ---------------------------------------------------------------------------


class TestMemoryBridgeSidechannel:
    def test_memory_write_event_calls_bridge_sync(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        _seed_concern(runtime, "c-curiosity")
        store = runtime.dcn_store
        bridge = OpenClawMemoryBridge(dcn_store=store)
        install_hooks(host, runtime=runtime, bridge=bridge)

        host.fire(
            "agent.memory_write",
            {
                "host_round_id": "t-1",
                "payload": {
                    "key": "episodic.q42",
                    "value": "42",
                    "concern_id": "c-curiosity",
                },
            },
        )
        # log_activation lands on the in-memory dcn_store; pull it back
        # via activation_log on the store directly.
        log = list(store.activation_log(concern_id="c-curiosity"))
        assert len(log) == 1
        # Schema isn't standardised across stores yet — at minimum the
        # joinpoint id should reflect the memory key.
        first = log[0]
        assert any("episodic.q42" in str(v) for v in first.values())

    def test_memory_write_against_unknown_concern_does_not_crash(self) -> None:
        """No seeded concern → bridge swallows ``KeyError`` and the
        host's event loop keeps running."""
        host = FakeHost()
        runtime = _build_runtime()
        bridge = OpenClawMemoryBridge(dcn_store=runtime.dcn_store)
        install_hooks(host, runtime=runtime, bridge=bridge)
        host.fire(
            "agent.memory_write",
            {
                "host_round_id": "t-1",
                "payload": {"key": "k", "concern_id": "c-archived"},
            },
        )
        # No activation persisted because the concern wasn't there.
        assert list(runtime.dcn_store.activation_log(concern_id="c-archived")) == []

    def test_memory_write_without_bridge_does_not_raise(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        install_hooks(host, runtime=runtime)  # bridge=None
        host.fire(
            "agent.memory_write",
            {"host_round_id": "t-1", "payload": {"key": "k"}},
        )

    def test_non_memory_events_do_not_touch_bridge(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        # Sentinel bridge: if .sync gets called we'll know via the side
        # effect on `calls`.
        calls: list[Any] = []

        class _BridgeSpy(OpenClawMemoryBridge):
            def sync(self, memory_event: Any) -> Any:  # type: ignore[override]
                calls.append(memory_event)
                return super().sync(memory_event)

        install_hooks(host, runtime=runtime, bridge=_BridgeSpy())
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {"text": "hi"}})
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})
        assert calls == []

    def test_memory_event_with_flat_payload_falls_back(self) -> None:
        """Toy hosts emit memory events without the ``payload`` envelope.
        The bridge consumes the raw dict in that case."""
        host = FakeHost()
        runtime = _build_runtime()
        _seed_concern(runtime, "c-flat")
        store = runtime.dcn_store
        bridge = OpenClawMemoryBridge(dcn_store=store)
        install_hooks(host, runtime=runtime, bridge=bridge)
        host.fire(
            "agent.memory_write",
            # No outer "payload" envelope and no "event_name".
            {"key": "flat.k", "concern_id": "c-flat"},
        )
        log = list(store.activation_log(concern_id="c-flat"))
        assert len(log) == 1


# ---------------------------------------------------------------------------
# InstalledHooks.uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_uninstall_calls_every_unsubscribe(self) -> None:
        host = FakeHost()
        installed = install_hooks(host, runtime=_build_runtime())
        installed.uninstall()
        assert installed.is_installed is False
        # Every subscribed callback should have been removed.
        assert all(len(cbs) == 0 for cbs in host.subscriptions.values())
        # And unsubscribe should have run once per subscription.
        assert host.unsubscribe_count == len(OpenClawEventName)

    def test_uninstall_is_idempotent(self) -> None:
        host = FakeHost()
        installed = install_hooks(host, runtime=_build_runtime())
        installed.uninstall()
        installed.uninstall()  # second call no-ops
        assert host.unsubscribe_count == len(OpenClawEventName)

    def test_events_fired_after_uninstall_are_no_op(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        _seed_concern(runtime, "c-x")
        bridge = OpenClawMemoryBridge(dcn_store=runtime.dcn_store)
        installed = install_hooks(host, runtime=runtime, bridge=bridge)
        installed.uninstall()
        # No registered callbacks → fire is a no-op.
        host.fire(
            "agent.memory_write",
            {"payload": {"key": "k", "concern_id": "c-x"}},
        )
        assert list(runtime.dcn_store.activation_log(concern_id="c-x")) == []


# ---------------------------------------------------------------------------
# Pickup API — InstalledHooks.pending / apply_to / guard_tool_call
# ---------------------------------------------------------------------------


def _session_start_concern() -> Concern:
    """The OpenClaw scaffold's ``runtime_start`` concern, inlined.

    Kept in-test rather than imported from the CLI scaffold so the
    host package doesn't grow a hard dep on ``opencoat_runtime_cli``.
    The shape mirrors
    ``opencoat_runtime_cli.plugin_templates.openclaw.concerns._opencoat_session_start``
    exactly — change it there and here together.
    """
    return Concern(
        id="c-session-start",
        name="session-start hint",
        description="Inserts an OpenCOAT-runtime hint on runtime_start.",
        pointcut=Pointcut(joinpoints=["runtime_start"]),
        advice=Advice(
            type=AdviceType.RESPONSE_REQUIREMENT,
            content="You are running under the OpenCOAT runtime. Be concise.",
        ),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.PROMPT_LEVEL,
            target="runtime_prompt.active_concerns",
            priority=0.5,
        ),
    )


def _seed_runnable_concern(runtime: OpenCOATRuntime, concern: Concern) -> None:
    """Seed a concern into both the concern store AND the DCN.

    The concern store drives matching / weaving; the DCN node lets
    ``log_activation`` succeed when the concern actually fires.
    """
    runtime.concern_store.upsert(concern)
    runtime.dcn_store.add_node(concern)


class _FakeRuntime:
    """Minimal :class:`RuntimeLike` returning a canned injection.

    Used for the unit-style pickup tests where we want to exercise the
    callback → buffer → apply_to wiring without spinning a real
    :class:`OpenCOATRuntime`. ``responses`` is a dict keyed by joinpoint
    name; missing keys return ``None`` (i.e. "no concern matched").
    """

    def __init__(self, responses: dict[str, ConcernInjection | None] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[JoinpointEvent] = []

    def on_joinpoint(
        self,
        jp: JoinpointEvent,
        *,
        context: dict[str, Any] | None = None,
        return_none_when_empty: bool = False,
    ) -> ConcernInjection | None:
        self.calls.append(jp)
        return self._responses.get(jp.name)


def _injection_with(target: str, content: str, *, weave_id: str = "t-1") -> ConcernInjection:
    return ConcernInjection(
        weave_id=weave_id,
        injections=[
            Injection(
                concern_id="c-test",
                target=target,
                content=content,
                mode=WeavingOperation.INSERT,
            )
        ],
    )


def _tool_guard_injection(*, weave_id: str = "t-1") -> ConcernInjection:
    return ConcernInjection(
        weave_id=weave_id,
        injections=[
            Injection(
                concern_id="c-guard",
                target="tool_call.arguments.command",
                content="refused by policy: rm -rf",
                mode=WeavingOperation.BLOCK,
            )
        ],
    )


class TestPendingBufferCapture:
    """The callbacks installed by :func:`install_hooks` must capture
    every non-empty :class:`ConcernInjection` the runtime returns onto
    :attr:`InstalledHooks.pending` so the host can pick it up via
    :meth:`apply_to` / :meth:`guard_tool_call`.
    """

    def test_pending_is_empty_before_any_event(self) -> None:
        host = FakeHost()
        installed = install_hooks(host, runtime=_FakeRuntime())
        assert installed.pending == ()

    def test_non_empty_injection_is_buffered(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime(
            {"on_user_input": _injection_with("runtime_prompt.active_concerns", "be concise")}
        )
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {"text": "hi"}})

        assert len(installed.pending) == 1
        entry = installed.pending[0]
        assert isinstance(entry, PendingInjection)
        assert entry.joinpoint.name == "on_user_input"
        assert entry.injection.injections[0].content == "be concise"

    def test_empty_injection_is_dropped(self) -> None:
        """Runtime returning an injection with ``injections=[]`` (no
        concerns matched) does NOT earn a buffer slot — it would be a
        no-op at apply_to time and would muddy ``pending`` snapshots.
        """
        host = FakeHost()
        runtime = _FakeRuntime({"on_user_input": ConcernInjection(weave_id="t-1", injections=[])})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})
        assert installed.pending == ()

    def test_none_response_is_dropped(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({})  # every joinpoint → None
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})
        assert installed.pending == ()

    def test_pending_property_returns_tuple_not_internal_list(self) -> None:
        """Callers must not be able to mutate the live buffer through the
        ``pending`` property — only :meth:`apply_to`,
        :meth:`guard_tool_call`, :meth:`clear_pending` move rows.
        """
        host = FakeHost()
        runtime = _FakeRuntime(
            {"on_user_input": _injection_with("runtime_prompt.active_concerns", "x")}
        )
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})
        snap = installed.pending
        assert isinstance(snap, tuple)
        # Even if a caller tries to clear the snapshot, the live buffer
        # stays intact.
        snap = ()  # rebinding the local does nothing
        assert len(installed.pending) == 1


class TestApplyTo:
    def test_apply_to_folds_buffered_injection_into_context(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime(
            {"on_user_input": _injection_with("runtime_prompt.active_concerns", "be precise")}
        )
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        out = installed.apply_to({"runtime_prompt": {"active_concerns": ""}})
        assert out == {"runtime_prompt": {"active_concerns": "be precise"}}

    def test_apply_to_drains_by_default(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"on_user_input": _injection_with("runtime_prompt.note", "once")})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})
        assert len(installed.pending) == 1

        first = installed.apply_to({})
        second = installed.apply_to({})

        assert first == {"runtime_prompt": {"note": "once"}}
        # Buffer drained → second call applies nothing.
        assert second == {}
        assert installed.pending == ()

    def test_apply_to_drain_false_peeks_without_consuming(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"on_user_input": _injection_with("runtime_prompt.note", "twice")})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        first = installed.apply_to({}, drain=False)
        second = installed.apply_to({}, drain=False)

        assert first == second == {"runtime_prompt": {"note": "twice"}}
        assert len(installed.pending) == 1

    def test_apply_to_filters_by_joinpoint_name(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime(
            {
                "on_user_input": _injection_with("runtime_prompt.user", "u"),
                "runtime_start": _injection_with("runtime_prompt.start", "s"),
            }
        )
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.started", {})
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        # Only fold runtime_start injections — on_user_input stays buffered.
        out = installed.apply_to({}, joinpoint="runtime_start")
        assert out == {"runtime_prompt": {"start": "s"}}
        remaining = installed.pending
        assert len(remaining) == 1
        assert remaining[0].joinpoint.name == "on_user_input"

    def test_apply_to_accepts_none_context(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime(
            {"on_user_input": _injection_with("runtime_prompt.note", "from-empty")}
        )
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        out = installed.apply_to(None)
        assert out == {"runtime_prompt": {"note": "from-empty"}}

    def test_apply_to_skips_tool_guard_joinpoints(self) -> None:
        """``before_tool_call`` injections have a structured outcome
        surface (``guard_tool_call``) — folding them through the
        generic ``apply_to`` path would corrupt the ``tool_call.*``
        slot, so they're skipped (and stay buffered for the guard
        surface to consume).
        """
        host = FakeHost()
        runtime = _FakeRuntime({"before_tool_call": _tool_guard_injection()})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})

        out = installed.apply_to({"runtime_prompt": {"active_concerns": ""}})
        # ``tool_call.*`` row didn't leak into the prompt context.
        assert out == {"runtime_prompt": {"active_concerns": ""}}
        # And it stays buffered so guard_tool_call can pick it up.
        assert len(installed.pending) == 1
        assert installed.pending[0].joinpoint.name == "before_tool_call"

    def test_apply_to_with_empty_buffer_is_identity(self) -> None:
        host = FakeHost()
        installed = install_hooks(host, runtime=_FakeRuntime())
        ctx = {"runtime_prompt": {"active_concerns": "existing"}}
        out = installed.apply_to(ctx)
        assert out == ctx

    def test_apply_to_deep_copies_context_on_noop_path(self) -> None:
        """Codex P2 regression — when ``apply_to`` has no applicable
        rows (empty buffer, ``joinpoint=`` filtered out everything,
        or only tool-guard rows present) it still must hand back a
        dict the caller can mutate without leaking changes back to
        ``context``.

        A shallow ``dict(context)`` would only clone the top level,
        so nested dicts (a real-world prompt context always nests
        ``runtime_prompt.*`` under one node) stay aliased between
        ``context`` and the return value — later mutation of the
        return value silently corrupts the caller's original.
        """
        host = FakeHost()
        installed = install_hooks(host, runtime=_FakeRuntime())

        original: dict[str, Any] = {
            "runtime_prompt": {"active_concerns": "kept", "system": "be brief"},
            "memory_write": {"policy_note": ""},
        }
        out = installed.apply_to(original)

        # Mutate every nested slot in ``out``. None of these must
        # show up in ``original``.
        out["runtime_prompt"]["active_concerns"] = "MUTATED"
        out["runtime_prompt"]["system"] = "MUTATED"
        out["memory_write"]["policy_note"] = "MUTATED"
        out["new_top_level"] = {"x": 1}

        assert original == {
            "runtime_prompt": {"active_concerns": "kept", "system": "be brief"},
            "memory_write": {"policy_note": ""},
        }

    def test_apply_to_deep_copies_when_joinpoint_filter_excludes_all(
        self,
    ) -> None:
        """Same contract holds when there IS a buffered injection but
        ``joinpoint=`` filters it out — the no-op deep-copy branch
        must still fire.
        """
        host = FakeHost()
        runtime = _FakeRuntime({"on_user_input": _injection_with("runtime_prompt.note", "n")})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})
        assert len(installed.pending) == 1

        original: dict[str, Any] = {"runtime_prompt": {"active_concerns": "kept"}}
        out = installed.apply_to(original, joinpoint="runtime_start")

        out["runtime_prompt"]["active_concerns"] = "MUTATED"
        assert original["runtime_prompt"]["active_concerns"] == "kept"

    def test_apply_to_deep_copies_when_only_tool_guard_rows_buffered(
        self,
    ) -> None:
        """Same contract when the buffer is non-empty but every entry
        is a ``before_tool_call`` row (skipped by ``apply_to`` since
        ``guard_tool_call`` is the canonical surface for those).
        """
        host = FakeHost()
        runtime = _FakeRuntime({"before_tool_call": _tool_guard_injection()})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})
        assert len(installed.pending) == 1

        original: dict[str, Any] = {"runtime_prompt": {"active_concerns": "kept"}}
        out = installed.apply_to(original)

        out["runtime_prompt"]["active_concerns"] = "MUTATED"
        assert original["runtime_prompt"]["active_concerns"] == "kept"


class TestGuardToolCall:
    def test_returns_outcome_for_buffered_tool_guard_injection(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"before_tool_call": _tool_guard_injection()})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})

        outcome = installed.guard_tool_call(
            {"name": "shell.exec", "arguments": {"command": "rm -rf /"}}
        )
        assert outcome is not None
        assert outcome.blocked is True
        assert "refused" in outcome.block_reason.lower()

    def test_returns_none_when_no_tool_guard_buffered(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"on_user_input": _injection_with("runtime_prompt.note", "n")})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        outcome = installed.guard_tool_call({"name": "x", "arguments": {}})
        assert outcome is None
        # The non-tool-guard injection should still be buffered.
        assert len(installed.pending) == 1

    def test_drains_consumed_entry_by_default(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"before_tool_call": _tool_guard_injection()})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})

        assert installed.guard_tool_call({"name": "x", "arguments": {}}) is not None
        # Second call sees an empty buffer.
        assert installed.guard_tool_call({"name": "x", "arguments": {}}) is None
        assert installed.pending == ()

    def test_drain_false_lets_outcome_be_inspected_repeatedly(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"before_tool_call": _tool_guard_injection()})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})

        first = installed.guard_tool_call({"name": "x", "arguments": {"command": "x"}}, drain=False)
        second = installed.guard_tool_call(
            {"name": "x", "arguments": {"command": "x"}}, drain=False
        )
        assert first is not None and second is not None
        assert first.blocked == second.blocked
        assert len(installed.pending) == 1

    def test_walks_newest_to_oldest(self) -> None:
        """Multiple tool-guard injections buffered → guard_tool_call
        applies the **newest** one and drains it. Older ones stay
        buffered for the next call. This mirrors how a real host's
        tool-call loop walks: each in-flight call should be evaluated
        against the most-recently-emitted advice.
        """
        host = FakeHost()
        seq = [_tool_guard_injection(weave_id=f"t-{i}") for i in range(3)]
        runtime = _FakeRuntime({"before_tool_call": seq[0]})
        installed = install_hooks(host, runtime=runtime)

        # Three consecutive before_tool_call events. We push them via
        # the same response slot by re-binding the runtime's mapping.
        host.fire("agent.before_tool", {"host_round_id": "t-0", "payload": {}})
        runtime._responses["before_tool_call"] = seq[1]
        host.fire("agent.before_tool", {"host_round_id": "t-1", "payload": {}})
        runtime._responses["before_tool_call"] = seq[2]
        host.fire("agent.before_tool", {"host_round_id": "t-2", "payload": {}})

        # First guard_tool_call should consume the newest entry — weave_id t-2.
        installed.guard_tool_call({"name": "x", "arguments": {}})
        remaining = [e.injection.weave_id for e in installed.pending]
        assert remaining == ["t-0", "t-1"]


class TestClearPending:
    def test_clear_pending_empties_buffer(self) -> None:
        host = FakeHost()
        runtime = _FakeRuntime({"on_user_input": _injection_with("runtime_prompt.note", "drop me")})
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        assert len(installed.pending) == 1
        installed.clear_pending()
        assert installed.pending == ()

    def test_uninstall_does_not_clear_pending(self) -> None:
        """Host may still want to inspect / apply buffered injections
        after subscription teardown — e.g. during a clean shutdown.
        """
        host = FakeHost()
        runtime = _FakeRuntime(
            {"on_user_input": _injection_with("runtime_prompt.note", "still here")}
        )
        installed = install_hooks(host, runtime=runtime)
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {}})

        assert len(installed.pending) == 1
        installed.uninstall()
        assert installed.is_installed is False
        # Pending buffer survives teardown.
        assert len(installed.pending) == 1


class TestEndToEndWithRealRuntime:
    """Full chain against an in-process ``OpenCOATRuntime`` (no daemon).

    Closes the loop the M5 #31 PR left half-wired: subscribe →
    runtime.on_joinpoint → ConcernInjection → apply_to → host context
    visibly changed.

    The daemon path is mechanically identical because
    :class:`opencoat_runtime_host_sdk.Client` returns the same
    :class:`ConcernInjection` shape (verified by the SDK-side wire
    tests + ``HttpTransport``'s ``ConcernInjection.model_validate``
    deserialisation). Re-asserting the wire here would just shadow
    those tests; this test pins the **integration** between
    install_hooks and the runtime/adapter pair.
    """

    def test_fire_event_apply_to_yields_visible_prompt_change(self) -> None:
        host = FakeHost()
        runtime = _build_runtime()
        _seed_runnable_concern(runtime, _session_start_concern())
        installed = install_hooks(host, runtime=runtime)

        before = {"runtime_prompt": {"active_concerns": ""}}
        host.fire("agent.started", {"host_round_id": "t-1", "payload": {}})

        # Buffer should now hold the session-start injection.
        assert len(installed.pending) == 1
        assert installed.pending[0].joinpoint.name == "runtime_start"

        after = installed.apply_to(before)
        active = after["runtime_prompt"]["active_concerns"]
        # The injection lands as visible advice text in the prompt slot.
        assert "OpenCOAT" in active
        # Source context untouched — apply_injection deep-copies.
        assert before["runtime_prompt"]["active_concerns"] == ""

    def test_concern_with_no_match_yields_no_prompt_change(self) -> None:
        """A concern that doesn't match the fired joinpoint must NOT
        leak into the host context — pins that the pickup API doesn't
        accidentally apply unrelated buffered injections.
        """
        host = FakeHost()
        runtime = _build_runtime()
        _seed_runnable_concern(runtime, _session_start_concern())
        installed = install_hooks(host, runtime=runtime)

        # ``agent.user_message`` maps to ``on_user_input``, not
        # ``runtime_start`` — the session-start concern shouldn't fire.
        host.fire("agent.user_message", {"host_round_id": "t-1", "payload": {"text": "hello"}})

        out = installed.apply_to({"runtime_prompt": {"active_concerns": "base"}})
        assert out == {"runtime_prompt": {"active_concerns": "base"}}
        assert installed.pending == ()
