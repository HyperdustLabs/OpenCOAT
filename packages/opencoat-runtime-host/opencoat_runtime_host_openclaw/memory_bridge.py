"""Bridge OpenClaw memory writes to the OpenCOAT Deep Concern Network (M5 #31).

OpenClaw keeps its own mutable memory layer (vector store / key-value /
scratchpad). The OpenCOAT runtime owns a separate Deep Concern Network of
typed concerns. :class:`OpenClawMemoryBridge` is the thin reflection
layer that lets the two coexist:

1. Memory events are coerced through :class:`OpenClawMemoryEvent` so
   the bridge gets a typed, ``extra='forbid'`` view rather than a
   free-form dict — host drift is rejected loudly instead of silently
   becoming malformed DCN state.
2. When the event carries a ``concern_id`` and the bridge was wired
   with a :class:`~opencoat_runtime_core.ports.dcn_store.DCNStore`, the
   write is logged as an activation on that concern. The
   ``joinpoint_id`` argument is filled with the memory ``key`` so an
   ``activation_log`` consumer can correlate against the OpenClaw key
   namespace.
3. Memory events without a ``concern_id`` round-trip unchanged: the
   bridge is intentionally lossy in one direction so a host that
   hasn't yet learned to tag memory writes with concerns can still
   forward them through ``install_hooks`` without crashing.

The bridge does **not** create concerns from memory contents — that's
explicit DCN evolution work (M6+) and not something we want a
lifecycle hook to do implicitly. Likewise, memory writes referencing a
``concern_id`` that the DCN doesn't know about (archived, never
created, drifted between systems) are dropped silently rather than
raising — agents emit memory writes on their own cadence and crashing
the hook on every untracked concern would make the integration
unreliable.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Imported under TYPE_CHECKING-equivalent guard so the host-plugins
# package keeps a soft dependency on core: a host that wires only the
# adapter / injector / tool-guard surface doesn't pay the import cost.
try:
    from opencoat_runtime_core.ports import DCNStore
except ImportError:  # pragma: no cover - only triggered when core is absent
    DCNStore = None  # type: ignore[misc,assignment]


class OpenClawMemoryEvent(BaseModel):
    """Canonical wire shape for an OpenClaw memory event.

    Required: ``key``. Everything else is optional / auto-filled — the
    bridge is tolerant of toy hosts that emit just ``{"key": "..."}``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str = Field(min_length=1)
    """Memory key the host is operating on (write target, delete key, …)."""

    operation: Literal["write", "update", "delete"] = "write"
    """What the host did to ``key``. Defaults to ``write`` for legacy
    hosts that don't distinguish operations."""

    value: Any = None
    """The value being written / updated. ``None`` for deletes."""

    namespace: str | None = None
    """Optional logical bucket — e.g. ``"episodic"`` vs ``"semantic"``."""

    concern_id: str | None = None
    """When present, the bridge logs an activation on this concern.
    Hosts that haven't learned to tag memory writes leave it blank."""

    host_round_id: str | None = None
    """Host dialog round id, when known — helps DCN tooling correlate."""

    ts: datetime | None = None
    """Memory event timestamp. The bridge falls back to ``datetime.now(UTC)``."""

    metadata: dict[str, Any] | None = None
    """Host-specific extras the bridge forwards verbatim."""


class OpenClawMemoryBridge:
    """Reflect OpenClaw memory events onto the OpenCOAT DCN."""

    def __init__(self, dcn_store: Any | None = None) -> None:
        # Typed as ``Any`` so we don't fail import when the optional
        # ``opencoat_runtime_core`` extras aren't installed; the runtime
        # protocol is duck-typed (``log_activation`` method only).
        self._dcn_store = dcn_store

    @property
    def dcn_store(self) -> Any | None:
        """Expose the wired DCN store (or ``None``) for introspection."""
        return self._dcn_store

    def sync(
        self,
        memory_event: dict[str, Any] | OpenClawMemoryEvent,
    ) -> OpenClawMemoryEvent:
        """Validate ``memory_event`` and reflect it on the DCN.

        Returns the typed event so callers (and ``install_hooks``)
        can forward it without re-parsing. Idempotent on the DCN side
        when ``concern_id`` is missing or the store isn't wired —
        validation is the only effect.
        """
        ev = (
            memory_event
            if isinstance(memory_event, OpenClawMemoryEvent)
            else OpenClawMemoryEvent.model_validate(memory_event)
        )
        if self._dcn_store is not None and ev.concern_id is not None:
            # ``DCNStore`` implementations (e.g. ``MemoryDCNStore``)
            # raise ``KeyError`` for unknown concern ids. Treat that as
            # a soft miss — see module docstring rationale.
            with contextlib.suppress(KeyError):
                self._dcn_store.log_activation(
                    ev.concern_id,
                    ev.key,
                    # Activation weight isn't part of the OpenClaw event;
                    # surface a flat 1.0 so downstream rankers see "this
                    # concern was touched". Negative scores are reserved
                    # for explicit decay events the heartbeat loop emits.
                    1.0,
                    ev.ts or datetime.now(tz=UTC),
                )
        return ev


__all__ = ["OpenClawMemoryBridge", "OpenClawMemoryEvent"]
