"""Metrics schema for MAN paper §8 tables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunMetrics:
    method: str
    success_rate: float
    llm_calls_per_success: float
    reliability_gap: float | None = None
    struct_stability: float | None = None
    spurious_split_rate: float | None = None
    mean_reward: float | None = None
    edges: int = 0
    aspects: int = 0
    splits: int = 0
    merges: int = 0
    replay_hash: str | None = None
    conservation_max_abs_residual: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentReport:
    hypotheses: dict[str, dict[str, Any]] = field(default_factory=dict)
    main_table: list[RunMetrics] = field(default_factory=list)
    ablation_table: list[RunMetrics] = field(default_factory=list)
    sweeps: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    empirical_gates: dict[str, bool] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "hypotheses": self.hypotheses,
                "main_table": [m.to_dict() for m in self.main_table],
                "ablation_table": [m.to_dict() for m in self.ablation_table],
                "sweeps": self.sweeps,
                "empirical_gates": self.empirical_gates,
                "raw": self.raw,
            },
            indent=2,
        )


def tier1_replay_hash(store_state: dict[str, Any]) -> str:
    payload = json.dumps(store_state, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


__all__ = ["ExperimentReport", "RunMetrics", "tier1_replay_hash"]
