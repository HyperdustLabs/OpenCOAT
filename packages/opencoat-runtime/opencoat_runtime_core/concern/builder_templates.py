"""Template resolution for :class:`ConcernBuilder` (v0.1 §20.3 MVP).

Maps extractor output (``generated_type``, ``generated_tags``, ``source.origin``)
to joinpoints, advice type, and weaving defaults. Hand-authored concerns that
already define ``pointcut`` / ``advice`` are left untouched by the builder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from opencoat_runtime_protocol import AdviceType, Concern

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "with",
        "from",
        "this",
        "must",
        "shall",
        "should",
        "never",
        "always",
        "when",
        "your",
        "into",
        "about",
        "rule",
        "concern",
    }
)

# (substring in normalized generated_type, advice_type, joinpoints, priority)
_TYPE_RULES: Final[tuple[tuple[str, AdviceType, tuple[str, ...], float], ...]] = (
    ("tool", AdviceType.TOOL_GUARD, ("before_tool_call",), 0.95),
    ("memory", AdviceType.MEMORY_WRITE_GUARD, ("before_memory_write",), 0.85),
    ("safety", AdviceType.TOOL_GUARD, ("before_response", "on_user_input"), 0.95),
    ("risk", AdviceType.TOOL_GUARD, ("before_response", "before_tool_call"), 0.9),
    ("malware", AdviceType.TOOL_GUARD, ("before_response",), 1.0),
    ("forbid", AdviceType.TOOL_GUARD, ("before_response", "before_tool_call"), 0.95),
    ("block", AdviceType.TOOL_GUARD, ("before_tool_call", "before_response"), 0.9),
    ("verify", AdviceType.VERIFICATION_RULE, ("before_response", "after_response"), 0.9),
    ("citation", AdviceType.VERIFICATION_RULE, ("before_response",), 0.85),
    ("cite", AdviceType.VERIFICATION_RULE, ("before_response",), 0.85),
    ("source", AdviceType.VERIFICATION_RULE, ("before_response",), 0.8),
    ("reason", AdviceType.REASONING_GUIDANCE, ("before_reasoning", "before_planning"), 0.7),
    ("plan", AdviceType.PLANNING_GUIDANCE, ("before_planning",), 0.7),
    ("persona", AdviceType.RESPONSE_REQUIREMENT, ("before_reasoning", "runtime_start"), 0.75),
    ("role", AdviceType.RESPONSE_REQUIREMENT, ("before_reasoning",), 0.75),
    ("style", AdviceType.RESPONSE_REQUIREMENT, ("before_response",), 0.7),
    ("preference", AdviceType.RESPONSE_REQUIREMENT, ("on_user_input", "before_response"), 0.65),
    ("constraint", AdviceType.RESPONSE_REQUIREMENT, ("before_response", "on_user_input"), 0.75),
    ("feedback", AdviceType.RESPONSE_REQUIREMENT, ("on_feedback",), 0.7),
    ("policy", AdviceType.RESPONSE_REQUIREMENT, ("on_user_input", "before_response"), 0.8),
)

_DEFAULT_JOINPOINTS: Final[tuple[str, ...]] = ("before_response", "on_user_input")
_DEFAULT_ADVICE: Final[AdviceType] = AdviceType.RESPONSE_REQUIREMENT
_DEFAULT_PRIORITY: Final[float] = 0.7


@dataclass(frozen=True, slots=True)
class ResolvedActivation:
    advice_type: AdviceType
    joinpoints: tuple[str, ...]
    priority: float = _DEFAULT_PRIORITY


def resolve_activation(concern: Concern) -> ResolvedActivation:
    """Pick advice type and joinpoints from extractor metadata."""
    gtype = (concern.generated_type or "").strip().lower()
    origin = (concern.source.origin if concern.source else "") or ""
    origin = origin.strip().lower()

    for needle, advice_type, joinpoints, priority in _TYPE_RULES:
        if needle in gtype:
            return ResolvedActivation(
                advice_type=advice_type,
                joinpoints=_origin_joinpoints(origin, joinpoints),
                priority=priority,
            )

    for tag in concern.generated_tags or []:
        tag_l = tag.strip().lower()
        for needle, advice_type, joinpoints, priority in _TYPE_RULES:
            if needle in tag_l:
                return ResolvedActivation(
                    advice_type=advice_type,
                    joinpoints=_origin_joinpoints(origin, joinpoints),
                    priority=priority,
                )

    if origin == "tool_result":
        return ResolvedActivation(
            advice_type=AdviceType.TOOL_GUARD,
            joinpoints=("before_tool_call", "before_response"),
            priority=0.85,
        )
    if origin in ("feedback",):
        return ResolvedActivation(
            advice_type=AdviceType.RESPONSE_REQUIREMENT,
            joinpoints=("on_feedback", "before_response"),
            priority=0.7,
        )

    return ResolvedActivation(
        advice_type=_DEFAULT_ADVICE,
        joinpoints=_origin_joinpoints(origin, _DEFAULT_JOINPOINTS),
        priority=_DEFAULT_PRIORITY,
    )


def activation_keywords(concern: Concern, *, limit: int = 12) -> list[str]:
    """Keywords for ``pointcut.match.any_keywords`` (may be empty)."""
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(raw: str) -> None:
        token = raw.strip().lower()
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            return
        seen.add(token)
        ordered.append(token)

    for tag in concern.generated_tags or []:
        _add(tag)
        if len(ordered) >= limit:
            return ordered

    for piece in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", concern.name.lower()):
        _add(piece)
        if len(ordered) >= limit:
            return ordered

    desc = (concern.description or "").lower()
    for piece in re.findall(r"[a-z]{4,}", desc):
        _add(piece)
        if len(ordered) >= limit:
            break

    return ordered


def _origin_joinpoints(origin: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    if origin == "tool_result" and "before_tool_call" not in defaults:
        return (*defaults, "before_tool_call")
    if origin in ("manual_import", "host_explicit_plan", "intent_alignment", "system_default"):
        extras = [jp for jp in ("on_user_input", "before_tool_call") if jp not in defaults]
        return (*defaults, *extras)
    return defaults


__all__ = ["ResolvedActivation", "activation_keywords", "resolve_activation"]
