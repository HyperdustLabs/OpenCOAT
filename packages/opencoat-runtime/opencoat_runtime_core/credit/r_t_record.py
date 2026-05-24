"""Structured effector outcome records ``r_t`` (v0.3 §10.1 step 3 prototype)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RtSignalKind = Literal[
    "tool_outcome",
    "tool_blocked",
    "llm_output",
    "turn_complete",
    "reflex_decision",
]

RECORD_VERSION = 1
EVENT_R_T = "r_t"


class RtSignal(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: RtSignalKind
    tool_name: str | None = None
    blocked: bool | None = None
    error: str | None = None
    duration_ms: float | None = None
    reflex: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RtRecord(BaseModel):
    """One append-only JSONL line for credit / plasticity consumption."""

    model_config = ConfigDict(extra="forbid")

    record_version: int = RECORD_VERSION
    event: Literal["r_t"] = EVENT_R_T
    ts: datetime
    session_id: str
    turn_id: str
    joinpoint: str
    host: str = "openclaw"
    hook: str
    signal: RtSignal
    r: float = Field(description="Observed reward (prototype: 0|1).")
    baseline_b: float = 0.0

    def to_jsonl(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def reward_from_signal(signal: RtSignal) -> float:
    """Prototype tier-1 reward: success=1, block/error=0."""
    if signal.kind == "tool_blocked":
        return 0.0
    if signal.kind == "tool_outcome":
        if signal.blocked:
            return 0.0
        if signal.error:
            return 0.0
        return 1.0
    if signal.kind == "turn_complete":
        if signal.error:
            return 0.0
        return 1.0
    return 0.0


__all__ = [
    "EVENT_R_T",
    "RECORD_VERSION",
    "RtRecord",
    "RtSignal",
    "RtSignalKind",
    "reward_from_signal",
]
