"""Warm-path plasticity: reweight concerns from structured ``r_t`` (v0.3 §3.6 subset)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opencoat_runtime_protocol import Concern

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.connectome_plasticity import (
    connect_coactivated,
    find_lift_candidates,
    find_merge_candidates,
    lift_coalition,
    merge_near_duplicate_pair,
    prune_weak_edges,
    split_with_spec_or_keywords,
)
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.credit.split_spec import evaluate_split_guards
from opencoat_runtime_core.credit.tier2_calibration import Tier2Calibrator
from opencoat_runtime_core.connectome.model import build_connectome_view
from opencoat_runtime_core.ports import ConcernStore, DCNStore


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


@dataclass(frozen=True)
class WarmStepStats:
    reinforced: int = 0
    weakened: int = 0
    connected: int = 0
    pruned: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "reinforced": self.reinforced,
            "weakened": self.weakened,
            "connected": self.connected,
            "pruned": self.pruned,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class ColdStepStats:
    lifted: int = 0
    archived: int = 0
    split: int = 0
    merged: int = 0
    lifted_aspect: int = 0
    connected: int = 0
    pruned: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "lifted": self.lifted,
            "archived": self.archived,
            "split": self.split,
            "merged": self.merged,
            "lifted_aspect": self.lifted_aspect,
            "connected": self.connected,
            "pruned": self.pruned,
            "skipped": self.skipped,
        }


class PlasticityEngine:
    """``⇩_slow`` reweight + connect/prune (warm) + split/lift/merge (cold)."""

    DEFAULT_DELTA = 0.05
    LIFT_SCORE = 0.75
    ARCHIVE_SCORE = 0.08
    SPLIT_SCORE = 0.65
    SPLIT_MIN_ACTIVATIONS = 3
    DEFAULT_TEMPERATURE = 1.0

    def __init__(
        self,
        *,
        step_delta: float = DEFAULT_DELTA,
        temperature: float = DEFAULT_TEMPERATURE,
        tier2: Tier2Calibrator | None = None,
    ) -> None:
        if not 0.0 < step_delta <= 1.0:
            raise ValueError(f"step_delta must be in (0, 1]; got {step_delta!r}")
        self._step_delta = step_delta
        self._temperature = temperature
        self._tier2 = tier2 or Tier2Calibrator()

    def warm_step(
        self,
        records: list[RtRecord],
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        lifecycle: ConcernLifecycleManager,
        co_pairs: list[tuple[str, str]] | None = None,
    ) -> WarmStepStats:
        reweight = self.reweight(records, concern_store=concern_store, lifecycle=lifecycle)
        connected = connect_coactivated(
            concern_store=concern_store,
            dcn_store=dcn_store,
            co_pairs=co_pairs or [],
        )
        pruned = prune_weak_edges(concern_store=concern_store, dcn_store=dcn_store)
        return WarmStepStats(
            reinforced=reweight.reinforced,
            weakened=reweight.weakened,
            connected=connected,
            pruned=pruned,
            skipped=reweight.skipped,
        )

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
            return self._attribute_policy(record, concern_id=policy_id.strip(), reflex=reflex)

        if record.signal.kind in {"llm_output", "turn_complete"}:
            return None, 0.0

        return None, 0.0

    def _attribute_policy(
        self,
        record: RtRecord,
        *,
        concern_id: str,
        reflex: dict[str, Any] | None,
    ) -> tuple[str | None, float]:
        """Attribute rows that carry a reflex ``policy_id`` (tool guard outcomes)."""
        if record.signal.kind == "tool_blocked":
            return concern_id, +1.0

        decision = reflex.get("decision") if reflex else None
        if decision == "deny":
            return concern_id, +1.0

        if record.signal.kind == "tool_outcome":
            advantage = record.r - record.baseline_b
            if advantage > 0:
                return concern_id, advantage
            if advantage < 0:
                return concern_id, advantage
            if record.signal.error:
                return concern_id, -1.0
            return None, 0.0

        advantage = record.r - record.baseline_b
        if advantage > 0:
            return concern_id, advantage
        if advantage < 0:
            return concern_id, advantage
        return None, 0.0

    def cold_step(
        self,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        lifecycle: ConcernLifecycleManager,
        buffer: ConcernRtBuffer | None = None,
    ) -> ColdStepStats:
        """Cold: ΔF-gated split, reflex lift, merge, archive, connectome lift."""
        rt_buffer = buffer or ConcernRtBuffer()
        lifted = 0
        archived = 0
        split = 0
        merged = 0
        lifted_aspect = 0
        skipped = 0

        view = build_connectome_view(concern_store=concern_store, dcn_store=dcn_store)

        for concern in list(concern_store.list()):
            if concern.lifecycle_state in {"archived", "merged", "deleted"}:
                skipped += 1
                continue
            score = concern.activation_state.score if concern.activation_state is not None else None
            if score is None:
                skipped += 1
                continue
            if concern.reflex:
                skipped += 1
                continue
            try:
                if self._should_split(concern, score=score, buffer=rt_buffer):
                    guard = evaluate_split_guards(
                        rt_buffer,
                        concern.id,
                        temperature=self._temperature,
                    )
                    if guard.partition is not None and guard.eligible:
                        self._tier2.calibrate_split(
                            concern.id,
                            tier1_gain=guard.partition.separability_gain,
                            context=guard.reason,
                        )
                    if split_with_spec_or_keywords(
                        concern=concern,
                        concern_store=concern_store,
                        buffer=rt_buffer,
                        lifecycle=lifecycle,
                        guard=guard,
                    ):
                        split += 1
                        continue
                if score >= self.LIFT_SCORE and concern.lifecycle_state == "reinforced":
                    updated = concern.model_copy(update={"reflex": True})
                    concern_store.upsert(updated)
                    lifted += 1
                elif score <= self.ARCHIVE_SCORE and concern.lifecycle_state == "weakened":
                    lifecycle.archive(concern, reason="cold plasticity: score below threshold")
                    archived += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1

        for a, b in find_merge_candidates(view)[:4]:
            if merge_near_duplicate_pair(
                concern_store=concern_store,
                dcn_store=dcn_store,
                a_id=a,
                b_id=b,
            ):
                merged += 1

        for coalition in find_lift_candidates(view)[:2]:
            coalition_id = f"lift.{'--'.join(coalition)}"
            if lift_coalition(
                concern_store=concern_store,
                members=coalition,
                coalition_id=coalition_id,
            ):
                lifted_aspect += 1

        pruned = prune_weak_edges(concern_store=concern_store, dcn_store=dcn_store)

        return ColdStepStats(
            lifted=lifted,
            archived=archived,
            split=split,
            merged=merged,
            lifted_aspect=lifted_aspect,
            pruned=pruned,
            skipped=skipped,
        )

    def _should_split(
        self,
        concern: Concern,
        *,
        score: float,
        buffer: ConcernRtBuffer,
    ) -> bool:
        if concern.lifecycle_state != "reinforced":
            return False
        if score < self.SPLIT_SCORE:
            return False
        if concern.metrics.activations < self.SPLIT_MIN_ACTIVATIONS:
            return False
        if buffer.count(concern.id) >= 8:
            return evaluate_split_guards(
                buffer,
                concern.id,
                temperature=self._temperature,
            ).eligible
        from opencoat_runtime_core.credit.connectome_split import propose_keyword_split

        return propose_keyword_split(concern) is not None


def concern_ids_from_records(records: list[RtRecord]) -> list[str]:
    engine = PlasticityEngine()
    ids: list[str] = []
    for rec in records:
        cid, direction = engine._attribute(rec)
        if cid and direction != 0:
            ids.append(cid)
    return ids


__all__ = [
    "ColdStepStats",
    "PlasticityEngine",
    "ReweightStats",
    "WarmStepStats",
    "concern_ids_from_records",
]
