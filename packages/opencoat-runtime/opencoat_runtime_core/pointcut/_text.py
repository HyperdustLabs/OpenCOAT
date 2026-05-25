"""Text extraction helpers shared across keyword / regex / semantic / token strategies.

Each :class:`JoinpointEvent` carries a payload whose textual content lives
under different keys depending on the level (``raw_text`` for messages,
``text`` for spans, ``token`` for tokens, etc.). These helpers normalise
that into a single string so strategies don't repeat the boilerplate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from opencoat_runtime_protocol import JoinpointEvent


def extract_text(jp: JoinpointEvent) -> str:
    """Return the joinpoint's text content, joined by newlines.

    Looks at the most common text-bearing keys across the 8 payload kinds.
    Returns an empty string when nothing textual is present (e.g. runtime
    or structure_field events).
    """
    payload = jp.payload or {}
    parts: list[str] = []
    for key in ("raw_text", "text", "content", "token", "command"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return "\n".join(parts)


def iter_tokens(jp: JoinpointEvent) -> Iterable[str]:
    """Yield discrete tokens carried by the joinpoint, if any.

    Spans expose ``payload.tokens`` directly; token-level joinpoints carry
    a single ``payload.token``. For other levels, fall back to whitespace
    splitting :func:`extract_text` so token strategies still have signal.
    """
    payload = jp.payload or {}
    if isinstance(payload.get("tokens"), list):
        for tok in payload["tokens"]:
            if isinstance(tok, str) and tok:
                yield tok
        return
    single = payload.get("token")
    if isinstance(single, str) and single:
        yield single
        return
    text = extract_text(jp)
    if text:
        yield from text.split()


def payload_field(payload: Mapping[str, object] | None, dotted: str) -> object | _Missing:
    """Resolve a dotted path inside a payload-like mapping.

    Returns :data:`MISSING` when any segment is absent; this lets callers
    distinguish "field is None" from "field does not exist".
    """
    cur: object = payload or {}
    for segment in dotted.split("."):
        if not isinstance(cur, Mapping) or segment not in cur:
            return MISSING
        cur = cur[segment]
    return cur


class _Missing:
    """Sentinel for missing values in :func:`payload_field`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<MISSING>"


MISSING = _Missing()


__all__ = ["MISSING", "extract_text", "iter_tokens", "payload_field"]
