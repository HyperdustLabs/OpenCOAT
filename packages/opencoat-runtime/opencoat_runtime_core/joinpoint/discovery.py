"""Discover child joinpoints from coarse host surfaces and runtime signals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from opencoat_runtime_protocol import COPR, JoinpointEvent

from ..copr.parser import CoprParser
from ..loops.heartbeat_loop import HeartbeatReport
from .levels import JoinpointLevel

_ROLE_TO_MESSAGE_JOINPOINT: dict[str, str] = {
    "system": "system_message",
    "developer": "developer_message",
    "user": "user_message",
    "assistant": "assistant_message",
    "tool": "tool_message",
    "memory": "memory_message",
    "retrieved_context": "retrieved_context",
}


class JoinpointDiscovery:
    """Expand prompt-code surfaces and synthesize runtime-sourced joinpoints."""

    def __init__(
        self,
        *,
        parser: CoprParser | None = None,
        max_discovered: int = 64,
    ) -> None:
        self._parser = parser or CoprParser()
        self._max_discovered = max_discovered

    def expand(self, parent: JoinpointEvent) -> list[JoinpointEvent]:
        """Return ``parent`` plus message/section joinpoints derived from its payload."""
        copr = self._copr_from_payload(parent.payload)
        if copr is None:
            return [parent]
        discovered = self.discover_from_copr(copr, parent)
        if not discovered:
            return [parent]
        return [parent, *discovered]

    def discover_from_copr(self, copr: COPR, parent: JoinpointEvent) -> list[JoinpointEvent]:
        out: list[JoinpointEvent] = []
        for msg_idx, message in enumerate(copr.messages):
            if len(out) >= self._max_discovered:
                break
            jp_name = _ROLE_TO_MESSAGE_JOINPOINT.get(str(message.role), "user_message")
            text = message.raw_text or ""
            out.append(
                _child_joinpoint(
                    parent,
                    suffix=f"msg:{msg_idx}",
                    level=JoinpointLevel.MESSAGE,
                    name=jp_name,
                    payload={
                        "prompt_id": copr.prompt_id,
                        "message_index": msg_idx,
                        "role": message.role,
                        "raw_text": text,
                        "text": text,
                        "content": text,
                    },
                )
            )
            for sec_idx, section in enumerate(message.sections):
                if len(out) >= self._max_discovered:
                    break
                sec_text = section.raw_text or text
                out.append(
                    _child_joinpoint(
                        parent,
                        suffix=f"msg:{msg_idx}#sec:{section.path}",
                        level=JoinpointLevel.PROMPT_SECTION,
                        name=section.path,
                        payload={
                            "prompt_id": copr.prompt_id,
                            "message_index": msg_idx,
                            "section_index": sec_idx,
                            "path": section.path,
                            "raw_text": sec_text,
                            "text": sec_text,
                            "content": sec_text,
                        },
                    )
                )
        return out

    def runtime_tick_joinpoint(
        self,
        report: HeartbeatReport,
        *,
        host: str = "opencoat-runtime",
    ) -> JoinpointEvent:
        return JoinpointEvent(
            id=f"tick-{report.ts.strftime('%Y%m%dT%H%M%S%fZ')}",
            level=int(JoinpointLevel.RUNTIME),
            name="runtime_tick",
            host=host,
            ts=report.ts,
            payload={
                "candidate_count": report.candidate_count,
                "decay_count": report.decay_count,
                "merge_count": report.merge_count,
                "archive_count": report.archive_count,
                "conflict_count": report.conflict_count,
                "text": (
                    f"runtime_tick candidate_count={report.candidate_count} "
                    f"decay={report.decay_count}"
                ),
                "raw_text": (
                    f"runtime_tick candidate_count={report.candidate_count} "
                    f"decay={report.decay_count}"
                ),
            },
        )

    def joinpoint_from_event(
        self,
        event: dict[str, Any],
        *,
        host: str = "opencoat-runtime",
    ) -> JoinpointEvent | None:
        from .event_map import joinpoint_name_for_event

        ev_type = event.get("type")
        if not isinstance(ev_type, str):
            return None
        jp_name = joinpoint_name_for_event(ev_type)
        if jp_name is None:
            return None
        ts_raw = event.get("ts")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now().astimezone()
        payload = event.get("payload")
        body: dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
        body.setdefault("event_type", ev_type)
        return JoinpointEvent(
            id=f"ev-{uuid.uuid4().hex[:12]}",
            level=int(JoinpointLevel.LIFECYCLE),
            name=jp_name,
            host=host,
            agent_session_id=body.get("agent_session_id")
            if isinstance(body.get("agent_session_id"), str)
            else None,
            host_round_id=body.get("host_round_id")
            if isinstance(body.get("host_round_id"), str)
            else None,
            ts=ts,
            payload=body,
        )

    def _copr_from_payload(self, payload: dict[str, Any] | None) -> COPR | None:
        if not payload:
            return None
        if isinstance(payload.get("copr"), dict):
            return COPR.model_validate(payload["copr"])
        if "messages" in payload:
            return self._parser.parse(payload, prompt_id=payload.get("prompt_id"))  # type: ignore[arg-type]
        return None


def _child_joinpoint(
    parent: JoinpointEvent,
    *,
    suffix: str,
    level: JoinpointLevel,
    name: str,
    payload: dict[str, Any],
) -> JoinpointEvent:
    child_payload = dict(payload)
    child_payload["parent_joinpoint_id"] = parent.id
    child_payload["parent_joinpoint_name"] = parent.name
    if parent.host_round_id is not None:
        child_payload.setdefault("host_round_id", parent.host_round_id)
    return JoinpointEvent(
        id=f"{parent.id}#{suffix}",
        level=int(level),
        name=name,
        host=parent.host,
        agent_session_id=parent.agent_session_id,
        host_round_id=parent.host_round_id,
        ts=parent.ts,
        payload=child_payload,
    )


__all__ = ["JoinpointDiscovery"]
