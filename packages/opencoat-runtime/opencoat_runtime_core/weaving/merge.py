"""Merge multiple concern injections from one host surface / weave batch."""

from __future__ import annotations

from opencoat_runtime_protocol import ConcernInjection
from opencoat_runtime_protocol.envelopes import Injection, InjectionTotals


def merge_injections(
    *injections: ConcernInjection | None,
    weave_id: str | None = None,
    host_round_id: str | None = None,
) -> ConcernInjection | None:
    """Concatenate injection rows; later rows win on duplicate (concern_id, target)."""
    rows: list[Injection] = []
    seen: set[tuple[str, str]] = set()
    resolved_weave_id = weave_id or ""
    session: str | None = None
    resolved_host_round: str | None = host_round_id
    ts = None

    for inj in injections:
        if inj is None or not inj.injections:
            continue
        if not resolved_weave_id:
            resolved_weave_id = inj.weave_id
        session = inj.agent_session_id or session
        resolved_host_round = inj.host_round_id or resolved_host_round
        ts = inj.ts or ts
        for row in inj.injections:
            key = (row.concern_id, row.target)
            if key in seen:
                rows = [r for r in rows if (r.concern_id, r.target) != key]
            seen.add(key)
            rows.append(row)

    if not rows:
        return None

    totals = InjectionTotals(
        tokens=sum(_estimate_tokens(r.content) for r in rows),
        concern_count=len({r.concern_id for r in rows}),
        advice_count=len(rows),
    )
    return ConcernInjection(
        weave_id=resolved_weave_id,
        agent_session_id=session,
        host_round_id=resolved_host_round,
        ts=ts,
        injections=rows,
        totals=totals,
    )


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


__all__ = ["merge_injections"]
