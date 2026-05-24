"""Warm-path plasticity: reweight concerns from structured ``r_t`` (v0.3 §3.6 subset)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.ports import ConcernStore


@dataclass(frozen=True)
class ReweightStats:
    read: int = 0
    reinforced: int = 0
    weakened: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "read": self.read,
            "reinforced": self.reinforced,
            "weakened": self.weakened,
            "skipped": self.skipped,
        }


class PlasticityEngine:
    """Prototype ``⇩_slow`` reweight only — no split/lift/connect/prune yet."""

    DEFAULT_DELTA = 0.05

    def __init__(self, *, step_delta: float = DEFAULT_DELTA) -> None:
        if not 0.0 < step_delta <= 1.0:
            raise ValueError(f"step_delta must be in (0, 1]; got {step_delta!r}")
        self._step_delta = step_delta

    def reweight(
        self,
        records: list[RtRecord],
        *,
        concern_store: ConcernStore,
        lifecycle: ConcernLifecycleManager,
    ) -> ReweightStats:
        reinforced = 0
        weakened = 0
        skipped = 0
        for record in records:
            concern_id, direction = self._attribute(record)
            if concern_id is None or direction == 0:
                skipped += 1
                continue
            concern = concern_store.get(concern_id)
            if concern is None:
                skipped += 1
                continue
            state = concern.lifecycle_state
            if state == "archived":
                try:
                    concern = lifecycle.revive(concern)
                except Exception:
                    skipped += 1
                    continue
            delta = min(abs(direction) * self._step_delta, self._step_delta)
            try:
                if direction > 0:
                    lifecycle.reinforce(concern, delta=delta)
                    reinforced += 1
                else:
                    lifecycle.weaken(concern, delta=delta)
                    weakened += 1
            except Exception:
                skipped += 1
        return ReweightStats(
            read=len(records),
            reinforced=reinforced,
            weakened=weakened,
            skipped=skipped,
        )

    def _attribute(self, record: RtRecord) -> tuple[str | None, float]:
        """Map one ``r_t`` row to ``(concern_id, direction)`` for reweight."""
        reflex = record.signal.reflex if isinstance(record.signal.reflex, dict) else None
        policy_id = reflex.get("policy_id") if reflex else None
        if isinstance(policy_id, str) and policy_id.strip():
            concern_id = policy_id.strip()
            if record.signal.kind == "tool_blocked":
                return concern_id, +1.0
            decision = reflex.get("decision") if reflex else None
            if decision == "deny":
                return concern_id, +1.0
            advantage = record.r - record.baseline_b
            if advantage > 0:
                return concern_id, +advantage
            if advantage < 0:
                return concern_id, advantage
            return None, 0.0

        if record.signal.kind in {"llm_output", "turn_complete"}:
            return None, 0.0

        advantage = record.r - record.baseline_b
        if advantage > 0:
            return None, 0.0
        if advantage < 0:
            return None, 0.0
        return None, 0.0


def concern_ids_from_records(records: list[RtRecord]) -> list[str]:
    engine = PlasticityEngine()
    ids: list[str] = []
    for rec in records:
        cid, direction = engine._attribute(rec)
        if cid and direction != 0:
            ids.append(cid)
    return ids


__all__ = ["PlasticityEngine", "ReweightStats", "concern_ids_from_records"]
