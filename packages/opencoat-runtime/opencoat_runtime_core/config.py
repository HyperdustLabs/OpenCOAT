"""Runtime configuration objects.

These mirror the shape of the daemon ``default.yaml`` (see
``packages/opencoat-runtime-daemon/opencoat_runtime_daemon/config/default.yaml``).
Keep them framework-free so the core remains importable without the daemon.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RuntimeBudgets(BaseModel):
    """Hard caps applied by the coordinator and weaver."""

    model_config = ConfigDict(extra="forbid")

    max_active_concerns: int = Field(default=12, ge=1)
    max_injection_tokens: int = Field(default=800, ge=1)
    max_advice_per_concern: int = Field(default=2, ge=1)


class RuntimeLoops(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heartbeat_interval_seconds: float = Field(default=30.0, gt=0.0)
    #: When false, the daemon does not start the background heartbeat scheduler.
    heartbeat_enabled: bool = Field(default=True)


class JoinpointAutomation(BaseModel):
    """Joinpoint discovery and runtime-sourced weave triggers (JP automation P1/P2)."""

    model_config = ConfigDict(extra="forbid")

    #: Emit ``runtime_tick`` and run the joinpoint pipeline on :meth:`tick`.
    weave_on_tick: bool = Field(default=True)
    #: Drain the event queue on :meth:`tick` and weave mapped lifecycle joinpoints.
    process_events_on_tick: bool = Field(default=True)
    #: Expand ``messages`` / ``copr`` payloads into message- and section-level JPs.
    expand_prompt_surface: bool = Field(default=True)
    #: Cap discovered child joinpoints per coarse host submit (JP explosion guard).
    max_discovered_joinpoints: int = Field(default=64, ge=1)
    #: One store scan + single weave for expanded prompt surfaces (P3).
    batch_surface_weave: bool = Field(default=True)
    #: Segment message text into spans during COPR parse / discovery (P4).
    discover_spans: bool = Field(default=True)
    #: Emit token-level joinpoints per message (P4, capped).
    discover_tokens: bool = Field(default=False)
    max_token_joinpoints_per_message: int = Field(default=16, ge=0)
    #: After a surface weave, emit ``adviceexecution`` for meta / concern-of-concern pointcuts.
    emit_adviceexecution: bool = Field(default=True)
    #: Run ``concern.extract`` on user chat before weaving (``on_user_input`` / ``user_message``).
    extract_from_user_message: bool = Field(default=False)
    #: Skip extraction when derived chat text is shorter than this (chars).
    extract_min_message_chars: int = Field(default=24, ge=1)


class RuntimeConfig(BaseModel):
    """Top-level runtime configuration.

    The core reads the fields it needs; the daemon owns transport / storage /
    LLM configuration in a separate, layered config object.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.2"
    loops: RuntimeLoops = Field(default_factory=RuntimeLoops)
    budgets: RuntimeBudgets = Field(default_factory=RuntimeBudgets)
    joinpoint_automation: JoinpointAutomation = Field(default_factory=JoinpointAutomation)
