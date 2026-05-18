"""Built-in catalog of well-known joinpoint names.

Hosts may extend this catalog at runtime. The names listed here are the
ones every host adapter is expected to map onto.
"""

from __future__ import annotations

from dataclasses import dataclass

from .levels import JoinpointLevel


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    level: JoinpointLevel
    description: str = ""


# v0.1 §12.3 — Runtime joinpoints
_RUNTIME = (
    CatalogEntry("runtime_start", JoinpointLevel.RUNTIME, "runtime initialised"),
    CatalogEntry("runtime_stop", JoinpointLevel.RUNTIME, "runtime shutting down"),
    CatalogEntry("runtime_tick", JoinpointLevel.RUNTIME, "heartbeat tick"),
    CatalogEntry("runtime_error", JoinpointLevel.RUNTIME, "internal error"),
    CatalogEntry("runtime_recovery", JoinpointLevel.RUNTIME, "recovered from error"),
)

# v0.1 §12.4 — Agent lifecycle joinpoints
_LIFECYCLE = (
    CatalogEntry("on_user_input", JoinpointLevel.LIFECYCLE),
    CatalogEntry("before_reasoning", JoinpointLevel.LIFECYCLE),
    CatalogEntry("after_reasoning", JoinpointLevel.LIFECYCLE),
    CatalogEntry("before_planning", JoinpointLevel.LIFECYCLE),
    CatalogEntry("after_planning", JoinpointLevel.LIFECYCLE),
    CatalogEntry("before_tool_call", JoinpointLevel.LIFECYCLE),
    CatalogEntry("after_tool_call", JoinpointLevel.LIFECYCLE),
    CatalogEntry("before_response", JoinpointLevel.LIFECYCLE),
    CatalogEntry("after_response", JoinpointLevel.LIFECYCLE),
    CatalogEntry("before_memory_write", JoinpointLevel.LIFECYCLE),
    CatalogEntry("after_memory_write", JoinpointLevel.LIFECYCLE),
    CatalogEntry("on_error", JoinpointLevel.LIFECYCLE),
    CatalogEntry("on_feedback", JoinpointLevel.LIFECYCLE),
    CatalogEntry("on_heartbeat", JoinpointLevel.LIFECYCLE),
)

# v0.1 §12.5 — Message-level
_MESSAGE = (
    CatalogEntry("system_message", JoinpointLevel.MESSAGE),
    CatalogEntry("developer_message", JoinpointLevel.MESSAGE),
    CatalogEntry("user_message", JoinpointLevel.MESSAGE),
    CatalogEntry("assistant_message", JoinpointLevel.MESSAGE),
    CatalogEntry("tool_message", JoinpointLevel.MESSAGE),
    CatalogEntry("memory_message", JoinpointLevel.MESSAGE),
    CatalogEntry("retrieved_context", JoinpointLevel.MESSAGE),
)

# v0.1 §12.6 — Prompt-section level
_PROMPT_SECTION = (
    CatalogEntry("system_prompt.role_definition", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("system_prompt.rules", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("developer_prompt.task_constraints", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("user_prompt.original_request", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("runtime_prompt.active_concerns", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("runtime_prompt.tool_instructions", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("runtime_prompt.output_format", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("runtime_prompt.verification_rules", JoinpointLevel.PROMPT_SECTION),
    CatalogEntry("runtime_prompt.reasoning_guidance", JoinpointLevel.PROMPT_SECTION),
)

# v0.1 §12.7–§12.8 — Span / token (P4 discovery)
_SPAN_TOKEN = (
    CatalogEntry("semantic_span", JoinpointLevel.SEMANTIC_SPAN, "COPR semantic span"),
    CatalogEntry("token", JoinpointLevel.TOKEN, "visible token in prompt text"),
)

# AspectJ-style adviceexecution — meta / concern-of-concern (P4)
_ADVICEEXECUTION = (
    CatalogEntry("adviceexecution", JoinpointLevel.LIFECYCLE, "after advice was applied"),
)


class JoinpointCatalog:
    """In-memory registry of joinpoint names. Hosts may add custom entries."""

    def __init__(self, entries: tuple[CatalogEntry, ...] = ()) -> None:
        self._entries: dict[str, CatalogEntry] = {e.name: e for e in entries}

    def register(self, entry: CatalogEntry) -> None:
        self._entries[entry.name] = entry

    def get(self, name: str) -> CatalogEntry | None:
        return self._entries.get(name)

    def by_level(self, level: JoinpointLevel) -> list[CatalogEntry]:
        return [e for e in self._entries.values() if e.level == level]

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __iter__(self):
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


JOINPOINT_CATALOG = JoinpointCatalog(
    _RUNTIME + _LIFECYCLE + _MESSAGE + _PROMPT_SECTION + _SPAN_TOKEN + _ADVICEEXECUTION
)
"""Default catalog populated with the names from v0.1 §12.3–§12.6."""
