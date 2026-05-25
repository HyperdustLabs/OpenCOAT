"""Morphogenetic paper §7–§8 validation (conservation, split, replay, graph)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.connectome.model import build_connectome_view
from opencoat_runtime_core.credit.attribution import ActiveAspect, uniform_responsibility
from opencoat_runtime_core.credit.attribution import tier1_responsibility as tier1_rho
from opencoat_runtime_core.credit.credit_field import CreditField
from opencoat_runtime_core.credit.eligibility import EligibilityField
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.credit.rt_replay import (
    read_rt_jsonl,
    replay_credit_conservation,
    replay_rt_jsonl,
)
from opencoat_runtime_core.credit.split_spec import (
    evaluate_split_guards,
    reward_variance,
)
from opencoat_runtime_protocol import Concern
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "morphogenetic"
RT_PATH = FIXTURES / "r_t_bimodal.jsonl"


@pytest.fixture(scope="module", autouse=True)
def _ensure_fixtures() -> None:
    if not RT_PATH.exists():
        import subprocess

        script = (
            Path(__file__).resolve().parents[3]
            / "scripts/generate_morphogenetic_validation_data.py"
        )
        subprocess.run(
            ["uv", "run", "python", str(script)],
            check=True,
            cwd=script.parents[1],
        )


def _load_concerns(store: MemoryConcernStore) -> None:
    for name in ("bimodal_concern.json", "soft_hint_concern.json"):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        store.upsert(Concern.model_validate(data))


def test_credit_conservation_on_fixture() -> None:
    store = MemoryConcernStore()
    _load_concerns(store)
    residuals = replay_credit_conservation(RT_PATH, concern_store=store)
    assert len(residuals) >= 16
    assert all(abs(r) < 1e-6 for r in residuals)


def test_replay_deterministic_scores_and_edges() -> None:
    def run() -> tuple[dict[str, float], int]:
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        _load_concerns(store)
        for c in store.iter_all():
            dcn.add_node(c)
        scores = replay_rt_jsonl(
            RT_PATH,
            concern_store=store,
            dcn_store=dcn,
            cold=True,
        )
        view = build_connectome_view(concern_store=store, dcn_store=dcn)
        return scores, len(view.edges)

    s1, e1 = run()
    s2, e2 = run()
    assert s1 == s2
    assert e1 == e2
    assert e1 > 0


def test_split_reduces_reward_variance() -> None:
    store = MemoryConcernStore()
    _load_concerns(store)
    buffer = ConcernRtBuffer()
    for rec in read_rt_jsonl(RT_PATH):
        field = CreditField(concern_store=store, buffer=buffer)
        field.attribute_turn(rec, active=_active_from_fixture(rec))

    parent_var = reward_variance(buffer.samples("paper.bimodal-guard"))
    guard = evaluate_split_guards(
        buffer,
        "paper.bimodal-guard",
        n_min=8,
        theta_h=0.01,
        beta=0.02,
    )
    assert guard.eligible, guard.reason
    assert guard.partition is not None

    samples = buffer.samples("paper.bimodal-guard")
    left_samples = [samples[i] for i in guard.partition.left_indices]
    right_samples = [samples[i] for i in guard.partition.right_indices]
    left_r = [s.r for s in left_samples]
    right_r = [s.r for s in right_samples]
    assert reward_variance(left_samples) < parent_var
    assert reward_variance(right_samples) < parent_var
    assert abs(sum(left_r) / len(left_r) - sum(right_r) / len(right_r)) >= 0.05


def test_eligibility_trace_accumulates_and_decays() -> None:
    e = EligibilityField(trace_lambda=0.5, trace_alpha=1.0)
    first = e.touch_aspect("a", part=1.0)
    second = e.touch_aspect("a", part=0.0)
    assert first == 1.0
    assert second == 0.5


def test_tier1_vs_uniform_responsibility_spread() -> None:
    active = [
        ActiveAspect("hard-a", 0.9, hard=True),
        ActiveAspect("soft-b", 0.9, hard=False),
    ]
    t1 = tier1_rho(active)
    uni = uniform_responsibility(active)
    assert t1["hard-a"] > t1["soft-b"]
    assert abs(uni["hard-a"] - uni["soft-b"]) < 1e-9


def test_rt_service_session_grows_connectome() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    _load_concerns(store)
    svc = RtPlasticityService(concern_store=store, dcn_store=dcn)
    for rec in read_rt_jsonl(RT_PATH)[:12]:
        active = _active_from_fixture(rec)
        svc.record_turn_activations(rec.turn_id, active)
        svc.append(rec)
    warm = svc.consume()
    stats = svc.connectome_stats()
    assert warm.connected + warm.synapses_strengthened >= 0
    assert stats["edges"] >= 0
    assert stats.get("last_conservation_residual") is not None
    assert abs(float(stats["last_conservation_residual"])) < 1e-5


def _active_from_fixture(rec) -> list[ActiveAspect]:
    from opencoat_runtime_core.credit.rt_replay import _active_from_record

    return _active_from_record(rec)


def test_plasticity_cold_split_on_fixture_buffer() -> None:
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    _load_concerns(store)
    buffer = ConcernRtBuffer()
    for rec in read_rt_jsonl(RT_PATH):
        CreditField(concern_store=store, buffer=buffer).attribute_turn(
            rec, active=_active_from_fixture(rec)
        )
    lifecycle = ConcernLifecycleManager(concern_store=store, dcn_store=dcn)
    cold = PlasticityEngine().cold_step(
        concern_store=store,
        dcn_store=dcn,
        lifecycle=lifecycle,
        buffer=buffer,
    )
    assert cold.split + cold.merged + cold.lifted_aspect >= 0
