"""Credit field κ — attribute ``r_t`` to concerns (v0.3 §3.6 tier-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.ports import ConcernStore


@dataclass(frozen=True)
class CreditAttribution:
    concern_id: str
    kappa: float
    direction: float
    eligibility: float = 1.0
    responsibility: float = 1.0


@dataclass
class CreditField:
    """Map structured ``r_t`` rows to concern credit (conservation prototype)."""

    concern_store: ConcernStore
    buffer: ConcernRtBuffer = field(default_factory=ConcernRtBuffer)
    baseline_b: float = 0.0

    def attribute(self, record: RtRecord) -> list[CreditAttribution]:
        """Attribute one row; update sample buffer; return κ assignments."""
        from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine

        engine = PlasticityEngine()
        concern_id, direction = engine._attribute(record)
        if concern_id is None or direction == 0.0:
            return []

        advantage = record.r - self.baseline_b
        kappa = advantage * direction
        feature = _feature_from_record(record)
        self.buffer.append(concern_id, r=record.r, feature=feature)

        concern = self.concern_store.get(concern_id)
        eligibility = 1.0
        if concern is not None and concern.metrics.activations > 0:
            eligibility = min(1.0, 0.1 + concern.metrics.activations * 0.05)

        return [
            CreditAttribution(
                concern_id=concern_id,
                kappa=kappa,
                direction=direction,
                eligibility=eligibility,
                responsibility=1.0,
            )
        ]

    def attribute_batch(self, records: list[RtRecord]) -> list[CreditAttribution]:
        out: list[CreditAttribution] = []
        for rec in records:
            out.extend(self.attribute(rec))
        return out

    def conserved_sum(self, attributions: list[CreditAttribution], *, r: float) -> float:
        """Check ``Σ κ ≈ r − b`` (tier-1 conservation diagnostic)."""
        return sum(a.kappa for a in attributions) - (r - self.baseline_b)


def _feature_from_record(record: RtRecord) -> str:
    payload = record.signal.payload if isinstance(record.signal.payload, dict) else {}
    for key in ("feature", "text", "content", "command"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    reflex = record.signal.reflex if isinstance(record.signal.reflex, dict) else {}
    pid = reflex.get("policy_id")
    return str(pid) if pid else record.joinpoint


__all__ = ["CreditAttribution", "CreditField"]
