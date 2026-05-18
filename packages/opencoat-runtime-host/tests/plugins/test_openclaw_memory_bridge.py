"""Tests for :class:`OpenClawMemoryBridge` + :class:`OpenClawMemoryEvent` (M5 #31)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from opencoat_runtime_host_openclaw import OpenClawMemoryBridge, OpenClawMemoryEvent
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


@dataclass
class _Activation:
    concern_id: str
    joinpoint_id: str
    score: float
    ts: datetime


@dataclass
class FakeDCNStore:
    """Records ``log_activation`` calls verbatim — duck-types DCNStore."""

    activations: list[_Activation] = field(default_factory=list)

    def log_activation(
        self,
        concern_id: str,
        joinpoint_id: str,
        score: float,
        ts: datetime,
    ) -> None:
        self.activations.append(
            _Activation(
                concern_id=concern_id,
                joinpoint_id=joinpoint_id,
                score=score,
                ts=ts,
            )
        )


# ---------------------------------------------------------------------------
# OpenClawMemoryEvent
# ---------------------------------------------------------------------------


class TestOpenClawMemoryEvent:
    def test_minimal_event_validates(self) -> None:
        ev = OpenClawMemoryEvent.model_validate({"key": "user.name"})
        assert ev.key == "user.name"
        assert ev.operation == "write"
        assert ev.value is None
        assert ev.concern_id is None

    def test_full_event_round_trips(self) -> None:
        payload: dict[str, Any] = {
            "key": "episodic.q42",
            "operation": "update",
            "value": {"answer": 42},
            "namespace": "episodic",
            "concern_id": "c-curiosity",
            "host_round_id": "t-7",
            "ts": "2026-05-11T10:00:00Z",
            "metadata": {"source": "tool"},
        }
        ev = OpenClawMemoryEvent.model_validate(payload)
        assert ev.operation == "update"
        assert ev.namespace == "episodic"
        assert ev.concern_id == "c-curiosity"
        assert ev.metadata == {"source": "tool"}

    def test_empty_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OpenClawMemoryEvent.model_validate({"key": ""})

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OpenClawMemoryEvent.model_validate({"key": "x", "rogue": True})

    def test_invalid_operation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OpenClawMemoryEvent.model_validate({"key": "x", "operation": "purge"})


# ---------------------------------------------------------------------------
# OpenClawMemoryBridge.sync
# ---------------------------------------------------------------------------


class TestSyncWithoutStore:
    """No DCN store wired → bridge is validation-only."""

    def test_sync_returns_typed_event(self) -> None:
        bridge = OpenClawMemoryBridge()
        ev = bridge.sync({"key": "user.name", "value": "moss"})
        assert isinstance(ev, OpenClawMemoryEvent)
        assert ev.key == "user.name"
        assert ev.value == "moss"

    def test_sync_accepts_already_typed_event(self) -> None:
        bridge = OpenClawMemoryBridge()
        typed = OpenClawMemoryEvent(key="cached", operation="write")
        result = bridge.sync(typed)
        assert result is typed  # no re-validation when already typed

    def test_sync_rejects_invalid_payload(self) -> None:
        bridge = OpenClawMemoryBridge()
        with pytest.raises(ValidationError):
            bridge.sync({"value": "no-key"})


@dataclass
class FlakyDCNStore:
    """Raises ``KeyError`` for every ``log_activation`` call —
    mirrors the real ``MemoryDCNStore`` behaviour when a concern node
    hasn't been registered yet."""

    log_calls: list[tuple[str, str]] = field(default_factory=list)

    def log_activation(
        self,
        concern_id: str,
        joinpoint_id: str,
        score: float,
        ts: datetime,
    ) -> None:
        self.log_calls.append((concern_id, joinpoint_id))
        raise KeyError(f"unknown concern: {concern_id!r}")


class TestSyncWithStore:
    """DCN store wired → activations logged when concern_id present."""

    def test_sync_logs_activation_when_concern_id_present(self) -> None:
        store = FakeDCNStore()
        bridge = OpenClawMemoryBridge(dcn_store=store)
        ts = datetime(2026, 5, 11, 10, 0, tzinfo=UTC)
        bridge.sync(
            {
                "key": "episodic.q42",
                "value": "42",
                "concern_id": "c-curiosity",
                "ts": ts.isoformat(),
            }
        )
        assert len(store.activations) == 1
        act = store.activations[0]
        assert act.concern_id == "c-curiosity"
        assert act.joinpoint_id == "episodic.q42"
        assert act.score == 1.0
        assert act.ts == ts

    def test_sync_without_concern_id_does_not_log(self) -> None:
        store = FakeDCNStore()
        bridge = OpenClawMemoryBridge(dcn_store=store)
        bridge.sync({"key": "anonymous", "value": "x"})
        assert store.activations == []

    def test_sync_fills_ts_when_missing(self) -> None:
        store = FakeDCNStore()
        bridge = OpenClawMemoryBridge(dcn_store=store)
        before = datetime.now(tz=UTC)
        bridge.sync({"key": "k", "concern_id": "c-1"})
        after = datetime.now(tz=UTC)
        assert len(store.activations) == 1
        assert before <= store.activations[0].ts <= after

    def test_sync_logs_for_every_operation(self) -> None:
        """Delete operations log activations too — they're still
        evidence the concern was relevant on this turn."""
        store = FakeDCNStore()
        bridge = OpenClawMemoryBridge(dcn_store=store)
        for op in ("write", "update", "delete"):
            bridge.sync({"key": f"k.{op}", "operation": op, "concern_id": "c-x"})
        assert [a.joinpoint_id for a in store.activations] == [
            "k.write",
            "k.update",
            "k.delete",
        ]

    def test_dcn_store_property_exposes_wired_store(self) -> None:
        store = FakeDCNStore()
        bridge = OpenClawMemoryBridge(dcn_store=store)
        assert bridge.dcn_store is store

    def test_dcn_store_property_returns_none_when_unwired(self) -> None:
        assert OpenClawMemoryBridge().dcn_store is None

    def test_sync_swallows_unknown_concern_keyerror(self) -> None:
        """Memory writes against an archived / unknown concern must not
        crash the host's event loop — the bridge treats KeyError as a
        soft miss and the call still returns the validated event."""
        store = FlakyDCNStore()
        bridge = OpenClawMemoryBridge(dcn_store=store)
        ev = bridge.sync({"key": "k", "concern_id": "c-missing"})
        # Store was called once before raising — bridge attempted reflection.
        assert store.log_calls == [("c-missing", "k")]
        # And the validated event still surfaces to the caller.
        assert ev.concern_id == "c-missing"

    def test_sync_propagates_non_keyerror_failures(self) -> None:
        """Only ``KeyError`` is treated as a soft miss — other failures
        (programming errors, contract violations) must propagate."""

        class _ExplodingStore:
            def log_activation(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("storage offline")

        bridge = OpenClawMemoryBridge(dcn_store=_ExplodingStore())
        with pytest.raises(RuntimeError, match="storage offline"):
            bridge.sync({"key": "k", "concern_id": "c-x"})
