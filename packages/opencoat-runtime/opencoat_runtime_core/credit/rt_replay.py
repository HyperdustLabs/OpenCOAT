"""Deterministic replay of ``r_t.jsonl`` for plasticity tests (v0.3 §11 step 4)."""

from __future__ import annotations

import json
from pathlib import Path

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.ports import ConcernStore, DCNStore


def read_rt_jsonl(path: Path | str) -> list[RtRecord]:
    """Load all ``r_t`` rows from a JSONL file (ignores tail cursor)."""
    records: list[RtRecord] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(RtRecord.model_validate(json.loads(line)))
    return records


def replay_rt_jsonl(
    path: Path | str,
    *,
    concern_store: ConcernStore,
    dcn_store: DCNStore,
    engine: PlasticityEngine | None = None,
) -> dict[str, float]:
    """Replay JSONL rows through reweight and return final concern scores."""
    records = read_rt_jsonl(path)
    plasticity = engine or PlasticityEngine()
    lifecycle = ConcernLifecycleManager(concern_store=concern_store, dcn_store=dcn_store)
    plasticity.reweight(records, concern_store=concern_store, lifecycle=lifecycle)
    scores: dict[str, float] = {}
    for concern in concern_store.list():
        if concern.activation_state is None or concern.activation_state.score is None:
            continue
        scores[concern.id] = concern.activation_state.score
    return scores


__all__ = ["read_rt_jsonl", "replay_rt_jsonl"]
