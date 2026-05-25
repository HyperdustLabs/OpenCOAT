"""Credit field κ — tier-1 conservation (morphogenetic §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from opencoat_runtime_core.credit.attribution import (
    ActiveAspect,
    tier1_responsibility,
    uniform_responsibility,
)
from opencoat_runtime_core.credit.baseline import RewardBaseline
from opencoat_runtime_core.credit.eligibility import EligibilityField
from opencoat_runtime_core.credit.r_t_record import RtRecord
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.ports import ConcernStore

ResponsibilityMode = Literal["tier1", "uniform"]


@dataclass(frozen=True)
class CreditAttribution:
    concern_id: str
    kappa: float
    direction: float
    eligibility: float
    responsibility: float


@dataclass(frozen=True)
class SynapseCredit:
    src: str
    dst: str
    relation: str
    kappa: float
    eligibility: float


@dataclass(frozen=True)
class CreditTurnResult:
    advantage: float
    baseline_b: float
    aspect_attributions: tuple[CreditAttribution, ...]
    synapse_attributions: tuple[SynapseCredit, ...]
    conservation_residual: float


@dataclass
class CreditField:
    """Map ``r_t`` to aspect + synapse credit with conservation and eligibility."""

    concern_store: ConcernStore
    buffer: ConcernRtBuffer = field(default_factory=ConcernRtBuffer)
    eligibility: EligibilityField = field(default_factory=EligibilityField)
    baseline: RewardBaseline = field(default_factory=RewardBaseline)
    responsibility_mode: ResponsibilityMode = "tier1"
    synapse_kappa_ledger: dict[tuple[str, str, str], float] = field(default_factory=dict)

    def attribute(
        self,
        record: RtRecord,
        *,
        active: list[ActiveAspect] | None = None,
    ) -> list[CreditAttribution]:
        return list(self.attribute_turn(record, active=active).aspect_attributions)

    def attribute_turn(
        self,
        record: RtRecord,
        *,
        active: list[ActiveAspect] | None = None,
    ) -> CreditTurnResult:
        bucket = self.baseline.bucket_for(
            joinpoint=record.joinpoint,
            session_id=record.session_id,
        )
        b = self.baseline.baseline(bucket)
        advantage = record.r - b
        self.baseline.update(bucket, record.r)

        aspects = list(active or [])
        if not aspects:
            aspects = self._fallback_active(record)

        rho = (
            tier1_responsibility(aspects)
            if self.responsibility_mode == "tier1"
            else uniform_responsibility(aspects)
        )

        raw_kappa: dict[str, float] = {}
        elig_map: dict[str, float] = {}
        for asp in aspects:
            e_a = self.eligibility.touch_aspect(asp.concern_id, part=asp.activation_score)
            elig_map[asp.concern_id] = e_a
            rho_a = rho.get(asp.concern_id, 0.0)
            raw_kappa[asp.concern_id] = advantage * e_a * rho_a

        aspect_attr = self._normalize_aspect_kappa(raw_kappa, advantage, elig_map, rho)

        synapse_attr = self._attribute_synapses(
            aspects,
            advantage=advantage,
            co_pairs=self._co_pairs(aspects),
        )

        feature = _feature_from_record(record)
        for attr in aspect_attr:
            self.buffer.append(attr.concern_id, r=record.r, feature=feature)

        residual = sum(a.kappa for a in aspect_attr) - advantage
        return CreditTurnResult(
            advantage=advantage,
            baseline_b=b,
            aspect_attributions=tuple(aspect_attr),
            synapse_attributions=tuple(synapse_attr),
            conservation_residual=residual,
        )

    def drain_synapse_ledger(self) -> list[tuple[str, str, float]]:
        """Return accumulated ``κ_s`` and reset (warm-path edge LTP driver)."""
        out: list[tuple[str, str, float]] = []
        for (src, dst, rel), kappa in list(self.synapse_kappa_ledger.items()):
            if rel != "activates":
                continue
            out.append((src, dst, kappa))
        self.synapse_kappa_ledger.clear()
        return out

    def conserved_sum(self, attributions: list[CreditAttribution], *, r: float) -> float:
        bucket = "default:"
        b = self.baseline.baseline(bucket)
        return sum(a.kappa for a in attributions) - (r - b)

    def _fallback_active(self, record: RtRecord) -> list[ActiveAspect]:
        from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine

        engine = PlasticityEngine()
        concern_id, _ = engine._attribute(record)
        if concern_id is None:
            return []
        reflex = record.signal.reflex if isinstance(record.signal.reflex, dict) else {}
        decision = reflex.get("decision")
        hard = record.signal.kind == "tool_blocked" or decision == "deny"
        return [ActiveAspect(concern_id=concern_id, activation_score=1.0, hard=hard)]

    def _normalize_aspect_kappa(
        self,
        raw: dict[str, float],
        advantage: float,
        elig: dict[str, float],
        rho: dict[str, float],
    ) -> list[CreditAttribution]:
        if not raw:
            return []
        total = sum(raw.values())
        scale = 1.0
        if abs(total) > 1e-9 and abs(advantage) > 1e-9:
            scale = advantage / total
        out: list[CreditAttribution] = []
        for cid, k in raw.items():
            out.append(
                CreditAttribution(
                    concern_id=cid,
                    kappa=k * scale,
                    direction=1.0 if k >= 0 else -1.0,
                    eligibility=elig.get(cid, 0.0),
                    responsibility=rho.get(cid, 0.0),
                )
            )
        return out

    def _co_pairs(self, aspects: list[ActiveAspect]) -> list[tuple[str, str]]:
        ids = [a.concern_id for a in aspects]
        pairs: list[tuple[str, str]] = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.append((ids[i], ids[j]))
        return pairs

    def _attribute_synapses(
        self,
        aspects: list[ActiveAspect],
        *,
        advantage: float,
        co_pairs: list[tuple[str, str]],
    ) -> list[SynapseCredit]:
        if not co_pairs or abs(advantage) < 1e-9:
            return []
        out: list[SynapseCredit] = []
        for a, b in co_pairs:
            for src, dst in ((a, b), (b, a)):
                e_s = self.eligibility.touch_synapse(src, dst, relation="activates", part=1.0)
                kappa_s = advantage * e_s
                key = (src, dst, "activates")
                self.synapse_kappa_ledger[key] = self.synapse_kappa_ledger.get(key, 0.0) + kappa_s
                out.append(
                    SynapseCredit(
                        src=src,
                        dst=dst,
                        relation="activates",
                        kappa=kappa_s,
                        eligibility=e_s,
                    )
                )
        return out


def _feature_from_record(record: RtRecord) -> str:
    """Stable stimulus axis for split buffer — never free-form LLM output text."""
    payload = record.signal.payload if isinstance(record.signal.payload, dict) else {}
    for key in ("feature", "feature_axis", "scenario_id", "task_class", "tool_name"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:128]
    if payload.get("phase") == "ii":
        return str(payload.get("scenario_id") or record.joinpoint).strip()[:128]
    reflex = record.signal.reflex if isinstance(record.signal.reflex, dict) else {}
    pid = reflex.get("policy_id")
    if isinstance(pid, str) and pid.strip():
        return pid.strip()
    for key in ("command",):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:128]
    return record.joinpoint


__all__ = [
    "CreditAttribution",
    "CreditField",
    "CreditTurnResult",
    "SynapseCredit",
]
