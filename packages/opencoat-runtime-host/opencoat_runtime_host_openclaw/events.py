"""Canonical wire shape for an OpenClaw lifecycle event (M5 #28).

OpenClaw doesn't ship a typed event SDK we can `import` — the adapter
**defines** the shape it expects, and any host that wants to drive
OpenCOAT through this plugin emits events that fit it. We keep the
contract tight (``extra='forbid'``) so payload drift surfaces as a
loud validation error instead of silently producing a malformed
:class:`~opencoat_runtime_protocol.JoinpointEvent` on the wire.

Mapping rules:

* ``event_name`` is a free-form string. Well-known values are
  enumerated in :class:`OpenClawEventName` and mapped to joinpoint
  names by :mod:`.joinpoint_map`; anything else returns ``None`` from
  :meth:`~.adapter.OpenClawAdapter.map_host_event`.
* ``id`` / ``ts`` are optional on input — the adapter fills sane
  defaults (``uuid4`` + current UTC time) so toy hosts can emit
  positional dicts without ceremony.
* ``payload`` is forwarded verbatim onto :class:`JoinpointEvent.payload`
  so downstream pointcut strategies (keyword / regex / structure / …)
  can inspect host-specific fields without the adapter having to
  flatten or rename anything.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpenClawEventName(StrEnum):
    """Well-known OpenClaw event names (v0.2 §4.7.1)."""

    AGENT_STARTED = "agent.started"
    AGENT_USER_MESSAGE = "agent.user_message"
    AGENT_BEFORE_LLM_CALL = "agent.before_llm_call"
    AGENT_AFTER_LLM_CALL = "agent.after_llm_call"
    AGENT_BEFORE_TOOL = "agent.before_tool"
    AGENT_AFTER_TOOL = "agent.after_tool"
    AGENT_BEFORE_RESPONSE = "agent.before_response"
    AGENT_AFTER_RESPONSE = "agent.after_response"
    AGENT_MEMORY_WRITE = "agent.memory_write"
    AGENT_ERROR = "agent.error"


class OpenClawEvent(BaseModel):
    """An OpenClaw event as it appears on the wire to the adapter.

    Required: ``event_name``.
    Optional / auto-filled: ``id``, ``ts``, ``agent_session_id``,
    ``host_round_id``, ``payload``. Legacy wire alias: ``turn_id``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_name: str = Field(min_length=1)
    id: str | None = None
    ts: datetime | None = None
    agent_session_id: str | None = None
    host_round_id: str | None = None
    payload: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_turn_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("turn_id") is not None:
            data = dict(data)
            if data.get("host_round_id") is None:
                data["host_round_id"] = data["turn_id"]
            data.pop("turn_id", None)
        return data


__all__ = ["OpenClawEvent", "OpenClawEventName"]
