"""Emit a joinpoint event from arbitrary host code.

:class:`JoinpointEmitter` is the canonical entry point any host adapter
(or hand-written host code) uses to feed events into the OpenCOAT
runtime. It builds a :class:`~opencoat_runtime_protocol.JoinpointEvent`
with the right envelope shape, submits it through the configured
:class:`~opencoat_runtime_host_sdk.client.Client`, and returns the
:class:`~opencoat_runtime_protocol.ConcernInjection` (if any) the
runtime decided to weave back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from opencoat_runtime_protocol import ConcernInjection, JoinpointEvent

from .client import Client


class JoinpointEmitter:
    """Build, submit, and return concern injections for host joinpoints."""

    def __init__(self, *, client: Client, host: str = "custom") -> None:
        self._client = client
        self._host = host

    @property
    def host(self) -> str:
        return self._host

    def emit(
        self,
        name: str,
        *,
        level: int = 1,
        agent_session_id: str | None = None,
        host_round_id: str | None = None,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        return_none_when_empty: bool = False,
    ) -> ConcernInjection | None:
        """Build a :class:`JoinpointEvent` and submit it via :attr:`_client`.

        Returns whatever :meth:`Client.emit` returns: the runtime's
        :class:`ConcernInjection` or ``None`` (when ``return_none_when_empty``
        is set and the runtime has nothing to inject).
        """
        jp = self.build(
            name,
            level=level,
            agent_session_id=agent_session_id,
            host_round_id=host_round_id,
            payload=payload,
        )
        return self._client.emit(jp, context=context, return_none_when_empty=return_none_when_empty)

    def build(
        self,
        name: str,
        *,
        level: int = 1,
        agent_session_id: str | None = None,
        host_round_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> JoinpointEvent:
        """Build a :class:`JoinpointEvent` *without* submitting it.

        Useful for callers that want to inspect / mutate the event
        before handing it back to :meth:`Client.emit` directly.
        """
        return JoinpointEvent(
            id=f"jp-{uuid4().hex[:12]}",
            level=level,
            name=name,
            host=self._host,
            agent_session_id=agent_session_id,
            host_round_id=host_round_id,
            ts=datetime.now(UTC),
            payload=payload,
        )


__all__ = ["JoinpointEmitter"]
