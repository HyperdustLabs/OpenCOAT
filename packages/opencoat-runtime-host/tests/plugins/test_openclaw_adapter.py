"""Behavioural tests for the OpenClaw event → joinpoint mapping (M5 #28).

This is the integration story for `OpenClawAdapter.map_host_event(s)`:
the file pins the wire contract every subsequent M5 PR will build on
(injector / span extractor / tool guard / memory bridge), so failures
here mean the host-to-runtime boundary moved.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from opencoat_runtime_core.joinpoint import JOINPOINT_CATALOG, JoinpointLevel
from opencoat_runtime_core.ports import HostAdapter
from opencoat_runtime_host_openclaw import (
    OPENCLAW_EVENT_MAP,
    OpenClawAdapter,
    OpenClawEvent,
    OpenClawEventName,
    lookup_joinpoint,
)
from opencoat_runtime_protocol import JoinpointEvent
from pydantic import ValidationError

# UUID-shaped string (case-insensitive) so tests can verify the
# adapter's id fallback without coupling to the exact uuid version.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@pytest.fixture
def adapter() -> OpenClawAdapter:
    return OpenClawAdapter()


# ----------------------------------------------------------------------
# joinpoint_map
# ----------------------------------------------------------------------


class TestJoinpointMap:
    def test_well_known_events_have_str_keyed_view(self) -> None:
        assert isinstance(OPENCLAW_EVENT_MAP, dict)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in OPENCLAW_EVENT_MAP.items())

    def test_every_well_known_event_is_in_the_map(self) -> None:
        # Catches regressions where someone adds an event name to the
        # enum but forgets to wire it into the mapping table.
        enum_values = {e.value for e in OpenClawEventName}
        assert enum_values == set(OPENCLAW_EVENT_MAP.keys())

    def test_every_mapped_target_is_in_the_v01_catalog(self) -> None:
        # The runtime would still accept an off-catalog joinpoint name,
        # but downstream tooling (catalog-driven docs, `opencoat inspect
        # joinpoints`) assumes catalog membership. Keep them aligned.
        for jp_name in OPENCLAW_EVENT_MAP.values():
            assert jp_name in JOINPOINT_CATALOG, f"missing from catalog: {jp_name!r}"

    def test_lookup_joinpoint_returns_none_for_unknown(self) -> None:
        assert lookup_joinpoint("not.a.real.openclaw.event") is None


# ----------------------------------------------------------------------
# OpenClawEvent
# ----------------------------------------------------------------------


class TestOpenClawEvent:
    def test_minimal_event_validates(self) -> None:
        oc = OpenClawEvent.model_validate({"event_name": "agent.user_message"})
        assert oc.event_name == "agent.user_message"
        assert oc.payload is None
        assert oc.ts is None
        assert oc.id is None

    def test_missing_event_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            OpenClawEvent.model_validate({"payload": {"text": "hi"}})

    def test_extra_top_level_keys_rejected(self) -> None:
        # extra="forbid" — host shape drift must trip an obvious error
        # rather than silently slipping through.
        with pytest.raises(ValidationError):
            OpenClawEvent.model_validate(
                {
                    "event_name": "agent.user_message",
                    "unexpected_field": "bad",
                }
            )


# ----------------------------------------------------------------------
# adapter / HostAdapter contract
# ----------------------------------------------------------------------


class TestAdapterContract:
    def test_satisfies_host_adapter_protocol(self, adapter: OpenClawAdapter) -> None:
        # Same check the M0 skeleton smoke test runs — must keep working.
        assert isinstance(adapter, HostAdapter)

    def test_host_name_is_openclaw(self, adapter: OpenClawAdapter) -> None:
        assert adapter.host_name == "openclaw"

    def test_apply_injection_merges_into_copy(self, adapter: OpenClawAdapter) -> None:
        from opencoat_runtime_protocol import ConcernInjection, Injection, WeavingOperation

        ctx = {"runtime_prompt": {"output_format": "Be brief."}}
        inj = ConcernInjection(
            weave_id="t-1",
            injections=[
                Injection(
                    concern_id="c-1",
                    target="runtime_prompt.output_format",
                    mode=WeavingOperation.INSERT,
                    content="Also cite sources.",
                )
            ],
        )
        out = adapter.apply_injection(inj, ctx)
        assert out["runtime_prompt"]["output_format"] == "Be brief.\nAlso cite sources."
        assert ctx["runtime_prompt"]["output_format"] == "Be brief."  # input untouched


# ----------------------------------------------------------------------
# map_host_event
# ----------------------------------------------------------------------


class TestMapHostEvent:
    @pytest.mark.parametrize(
        "event_name,joinpoint_name,expected_level",
        [
            ("agent.started", "runtime_start", JoinpointLevel.RUNTIME),
            ("agent.user_message", "on_user_input", JoinpointLevel.LIFECYCLE),
            ("agent.before_llm_call", "before_reasoning", JoinpointLevel.LIFECYCLE),
            ("agent.after_llm_call", "after_reasoning", JoinpointLevel.LIFECYCLE),
            ("agent.before_tool", "before_tool_call", JoinpointLevel.LIFECYCLE),
            ("agent.after_tool", "after_tool_call", JoinpointLevel.LIFECYCLE),
            ("agent.before_response", "before_response", JoinpointLevel.LIFECYCLE),
            ("agent.after_response", "after_response", JoinpointLevel.LIFECYCLE),
            ("agent.memory_write", "before_memory_write", JoinpointLevel.LIFECYCLE),
            ("agent.error", "on_error", JoinpointLevel.LIFECYCLE),
        ],
    )
    def test_known_event_produces_expected_joinpoint(
        self,
        adapter: OpenClawAdapter,
        event_name: str,
        joinpoint_name: str,
        expected_level: JoinpointLevel,
    ) -> None:
        jp = adapter.map_host_event({"event_name": event_name})
        assert isinstance(jp, JoinpointEvent)
        assert jp.name == joinpoint_name
        assert jp.level == int(expected_level)
        assert jp.host == "openclaw"

    def test_unknown_event_returns_none(self, adapter: OpenClawAdapter) -> None:
        jp = adapter.map_host_event({"event_name": "agent.totally_unknown"})
        assert jp is None

    def test_payload_passthrough_is_verbatim(self, adapter: OpenClawAdapter) -> None:
        payload: dict[str, Any] = {
            "text": "What is concern weaving?",
            "raw_text": "What is concern weaving?",
            "metadata": {"locale": "en-US"},
        }
        jp = adapter.map_host_event({"event_name": "agent.user_message", "payload": payload})
        assert jp is not None
        # Value-equality is the contract — pydantic may copy/clone the
        # mapping during validation, which is fine. What matters is
        # that nothing was renamed, dropped, or coerced on the way
        # through; downstream pointcut strategies see the OpenClaw
        # payload as-authored.
        assert jp.payload == payload

    def test_payload_round_trips_nested_structures(self, adapter: OpenClawAdapter) -> None:
        payload: dict[str, Any] = {
            "tool_name": "search",
            "arguments": {"q": "concern weaving", "limit": 5, "filters": []},
            "trace": [{"step": 1, "ok": True}, {"step": 2, "ok": False}],
        }
        jp = adapter.map_host_event({"event_name": "agent.before_tool", "payload": payload})
        assert jp is not None
        assert jp.payload == payload

    def test_session_and_host_round_id_propagate(self, adapter: OpenClawAdapter) -> None:
        jp = adapter.map_host_event(
            {
                "event_name": "agent.before_response",
                "agent_session_id": "sess-42",
                "host_round_id": "round-7",
            }
        )
        assert jp is not None
        assert jp.agent_session_id == "sess-42"
        assert jp.host_round_id == "round-7"

    def test_ts_propagates_when_supplied(self, adapter: OpenClawAdapter) -> None:
        fixed = datetime(2026, 5, 11, 22, 0, 0, tzinfo=UTC)
        jp = adapter.map_host_event({"event_name": "agent.user_message", "ts": fixed.isoformat()})
        assert jp is not None
        assert jp.ts == fixed

    def test_ts_defaults_to_now_utc_when_missing(self, adapter: OpenClawAdapter) -> None:
        before = datetime.now(tz=UTC)
        jp = adapter.map_host_event({"event_name": "agent.user_message"})
        after = datetime.now(tz=UTC)
        assert jp is not None
        assert before - timedelta(seconds=1) <= jp.ts <= after + timedelta(seconds=1)

    def test_id_propagates_when_supplied(self, adapter: OpenClawAdapter) -> None:
        jp = adapter.map_host_event({"event_name": "agent.user_message", "id": "evt-explicit-abc"})
        assert jp is not None
        assert jp.id == "evt-explicit-abc"

    def test_id_is_uuid_shaped_when_missing(self, adapter: OpenClawAdapter) -> None:
        jp = adapter.map_host_event({"event_name": "agent.user_message"})
        assert jp is not None
        assert _UUID_RE.match(jp.id), f"id is not uuid-shaped: {jp.id!r}"

    def test_two_unmarked_events_get_distinct_ids(self, adapter: OpenClawAdapter) -> None:
        a = adapter.map_host_event({"event_name": "agent.user_message"})
        b = adapter.map_host_event({"event_name": "agent.user_message"})
        assert a is not None and b is not None
        assert a.id != b.id

    def test_typed_openclaw_event_is_accepted(self, adapter: OpenClawAdapter) -> None:
        oc = OpenClawEvent(event_name="agent.before_response", host_round_id="t-1")
        jp = adapter.map_host_event(oc)
        assert jp is not None
        assert jp.name == "before_response"
        assert jp.host_round_id == "t-1"

    def test_invalid_dict_raises_validation_error(self, adapter: OpenClawAdapter) -> None:
        # Missing `event_name` — must fail loudly, not silently return
        # None (None is reserved for "known shape, unknown event name").
        with pytest.raises(ValidationError):
            adapter.map_host_event({"payload": {"text": "hi"}})


# ----------------------------------------------------------------------
# map_host_events
# ----------------------------------------------------------------------


class TestMapHostEvents:
    def test_streams_mappings_and_drops_unknowns(self, adapter: OpenClawAdapter) -> None:
        events: list[dict] = [
            {"event_name": "agent.user_message"},
            {"event_name": "agent.totally_unknown"},  # filtered
            {"event_name": "agent.before_response"},
            {"event_name": "agent.error"},
        ]
        result = list(adapter.map_host_events(events))
        names = [jp.name for jp in result]
        assert names == ["on_user_input", "before_response", "on_error"]

    def test_empty_input_yields_no_output(self, adapter: OpenClawAdapter) -> None:
        assert list(adapter.map_host_events([])) == []

    def test_lazy_generator_does_not_consume_eagerly(self, adapter: OpenClawAdapter) -> None:
        seen: list[str] = []

        def producer():
            for name in ("agent.user_message", "agent.before_response"):
                seen.append(name)
                yield {"event_name": name}

        stream = adapter.map_host_events(producer())
        # Pulling one element must not have consumed the second.
        first = next(iter(stream))
        assert first.name == "on_user_input"
        assert seen == ["agent.user_message"]
