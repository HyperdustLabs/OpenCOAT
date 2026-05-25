"""Deterministic replay of ``r_t.jsonl`` for plasticity + credit (morphogenetic §8)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.attribution import ActiveAspect
from opencoat_runtime_core.credit.credit_field import CreditField
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.credit.synapse_ledger import apply_synapse_kappa_ledger
from opencoat_runtime_core.ports import ConcernStore, DCNStore


def read_rt_jsonl(path: Path | str) -> list[RtRecord]:
    records: list[RtRecord] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(RtRecord.model_validate(json.loads(line)))
    return records


@dataclass
class ReplayState:
    credit: CreditField
    engine: PlasticityEngine
    turn_active: dict[str, list[ActiveAspect]] = field(default_factory=dict)
    conservation_residuals: list[float] = field(default_factory=list)


def replay_rt_jsonl(
    path: Path | str,
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    engine: PlasticityEngine | None = None,
    credit: CreditField | None = None,
    cold: bool = False,
) -> dict[str, float]:
    """Replay JSONL: credit attribution → warm → optional cold; return scores."""
    records = read_rt_jsonl(path)
    plasticity = engine or PlasticityEngine()
    field = credit or CreditField(concern_store=concern_store)
    lifecycle = ConcernLifecycleManager(concern_store=concern_store, dcn_store=dcn_store)

    co_pairs: list[tuple[str, str]] = []
    for rec in records:
        active = _active_from_record(rec)
        field.attribute_turn(rec, active=active)
        if len(active) >= 2:
            ids = sorted(a.concern_id for a in active)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    co_pairs.append((ids[i], ids[j]))

    plasticity.warm_step(
        records,
        concern_store=concern_store,
        dcn_store=dcn_store,
        lifecycle=lifecycle,
        co_pairs=co_pairs,
    )
    ledger = field.drain_synapse_ledger()
    apply_synapse_kappa_ledger(ledger, concern_store=concern_store, dcn_store=dcn_store)

    if cold:
        plasticity.cold_step(
            concern_store=concern_store,
            dcn_store=dcn_store,
            lifecycle=lifecycle,
            buffer=field.buffer,
        )

    scores: dict[str, float] = {}
    for concern in concern_store.list():
        if concern.activation_state is None or concern.activation_state.score is None:
            continue
        scores[concern.id] = concern.activation_state.score
    return scores


def replay_credit_conservation(path: Path | str, *, concern_store: ConcernStore) -> list[float]:
    """Return per-row conservation residuals ``Σκ_a − (r−b)``."""
    field = CreditField(concern_store=concern_store)
    residuals: list[float] = []
    for rec in read_rt_jsonl(path):
        result = field.attribute_turn(rec, active=_active_from_record(rec))
        residuals.append(result.conservation_residual)
    return residuals


def _active_from_record(record: RtRecord) -> list[ActiveAspect]:
    payload = record.signal.payload if isinstance(record.signal.payload, dict) else {}
    actors = payload.get("active_aspects")
    if isinstance(actors, list):
        out: list[ActiveAspect] = []
        for item in actors:
            if not isinstance(item, dict):
                continue
            cid = item.get("concern_id")
            if not isinstance(cid, str):
                continue
            score = float(item.get("activation_score", 1.0))
            hard = bool(item.get("hard", False))
            out.append(ActiveAspect(concern_id=cid, activation_score=score, hard=hard))
        if out:
            return out
    reflex = record.signal.reflex if isinstance(record.signal.reflex, dict) else {}
    pid = reflex.get("policy_id")
    if isinstance(pid, str) and pid.strip():
        hard = record.signal.kind == "tool_blocked" or reflex.get("decision") == "deny"
        return [ActiveAspect(concern_id=pid.strip(), activation_score=1.0, hard=hard)]
    return []


__all__ = [
    "ReplayState",
    "read_rt_jsonl",
    "replay_credit_conservation",
    "replay_rt_jsonl",
]
