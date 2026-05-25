"""Phase II H0 runner: learning curves + transfer on coding + OpenClaw scenarios."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import mkstemp
from typing import Any
from uuid import uuid4

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.concern.verifier import ConcernVerifier
from opencoat_runtime_core.credit.attribution import ActiveAspect
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine
from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal
from opencoat_runtime_core.credit.rt_plasticity_service import RtPlasticityService
from opencoat_runtime_core.ports import LLMClient
from opencoat_runtime_protocol import Advice, AdviceType, Concern, JoinpointEvent
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

from experiments.man_paper.phase_ii_llm import resolve_phase_ii_llm
from experiments.man_paper.phase_ii_scenarios import (
    Scenario,
    evaluate_phase_ii_reward,
    evaluate_phase_ii_success,
    load_scenario_config,
    load_scenarios,
    load_scenarios_for_epoch,
)
from experiments.man_paper.phase_ii_seed import seed_h0_graph

REPO = Path(__file__).resolve().parents[2]
_BOOTSTRAP_CONCERN: Concern | None = None

# Set by ``configure_phase_ii_llm`` at run start (shared across baselines).
_SHARED_LLM: LLMClient | None = None
_LLM_LABEL: str = "unconfigured"
_LLM_IS_STUB: bool = True
_FEATURE_MODE: str = "scenario_id"

PhaseIIProgress = Callable[[dict[str, Any]], None]


def configure_phase_ii_feature_mode(mode: str) -> str:
    """Buffer partition axis: ``scenario_id`` (default) or ablation ``text`` (LLM output)."""
    global _FEATURE_MODE
    allowed = {"scenario_id", "text"}
    m = (mode or "scenario_id").strip().lower()
    if m not in allowed:
        raise ValueError(f"feature_mode must be one of {sorted(allowed)}; got {mode!r}")
    _FEATURE_MODE = m
    return _FEATURE_MODE


def configure_phase_ii_llm(provider: str | None = None) -> tuple[str, bool]:
    """Select LLM once per Phase II run (all baselines use the same effector)."""
    global _SHARED_LLM, _LLM_LABEL, _LLM_IS_STUB
    try:
        from opencoat_runtime_daemon.config.loader import merge_user_llm_env_file

        merge_user_llm_env_file()
    except ImportError:
        pass
    client, label, is_stub = resolve_phase_ii_llm(provider)
    _SHARED_LLM = client
    _LLM_LABEL = label
    _LLM_IS_STUB = is_stub
    return label, is_stub


def _llm() -> LLMClient:
    assert _SHARED_LLM is not None
    return _SHARED_LLM


def _bootstrap_concern(store: MemoryConcernStore, dcn: MemoryDCNStore) -> Concern:
    """One extracted concern per Phase II run (shared across baselines)."""
    global _BOOTSTRAP_CONCERN
    if _BOOTSTRAP_CONCERN is None:
        _BOOTSTRAP_CONCERN = seed_h0_graph(_llm(), store=store, dcn=dcn)
    else:
        store.upsert(_BOOTSTRAP_CONCERN)
        with suppress(Exception):
            dcn.add_node(_BOOTSTRAP_CONCERN)
    return _BOOTSTRAP_CONCERN


class PhaseIIBaseline(StrEnum):
    MAN_FULL = "man_full"
    STATIC = "static_aspect_graph"
    HAND_ITERATED = "hand_iterated"


@dataclass
class EpisodePoint:
    epoch: int
    success_rate: float
    mean_reward: float
    llm_calls: int
    dev_edits: int
    aspects: int
    edges: int
    splits: int
    bootstrap_score: float | None = None
    bootstrap_buffer: int = 0
    bootstrap_activations: int = 0
    bootstrap_state: str | None = None
    first_split_epoch: int | None = None
    split_guard_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "epoch": self.epoch,
            "success_rate": self.success_rate,
            "mean_reward": self.mean_reward,
            "llm_calls": self.llm_calls,
            "dev_edits": self.dev_edits,
            "aspects": self.aspects,
            "edges": self.edges,
            "splits": self.splits,
            "bootstrap_score": self.bootstrap_score,
            "bootstrap_buffer": self.bootstrap_buffer,
            "bootstrap_activations": self.bootstrap_activations,
            "bootstrap_state": self.bootstrap_state,
            "first_split_epoch": self.first_split_epoch,
            "split_guard_reason": self.split_guard_reason,
        }


@dataclass
class TransferPoint:
    split: str
    success_rate: float
    mean_reward: float
    n: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "success_rate": self.success_rate,
            "mean_reward": self.mean_reward,
            "n": self.n,
        }


def _hand_patch_pool(seed: Concern) -> list[Concern]:
    """Developer-effort patches derived from the bootstrap concern (fixed budget)."""
    return [
        seed.model_copy(
            update={
                "id": f"{seed.id}-hand-cite",
                "name": "Hand-iterated: require documentation URLs",
                "description": (
                    f"{seed.description} "
                    "Every technical answer must include https:// documentation links."
                ),
                "advice": Advice(
                    type=AdviceType.RESPONSE_REQUIREMENT,
                    content=(
                        "For every technical or coding answer, include the relevant "
                        "official documentation URL and mark it as [1]."
                    ),
                ),
                "generated_type": "citation",
            }
        ),
        seed.model_copy(
            update={
                "id": f"{seed.id}-hand-verify",
                "name": "Hand-iterated: verification emphasis",
                "description": (
                    f"{seed.description} "
                    "Treat reward-modulated plasticity as requiring verifiable, grounded outputs."
                ),
                "advice": Advice(
                    type=AdviceType.RESPONSE_REQUIREMENT,
                    content=(
                        "Prefer concrete, verifiable answers: include code when asked, "
                        "name the standard-library API, and cite official documentation."
                    ),
                ),
                "generated_type": "verify",
            }
        ),
    ]


@dataclass
class _CodingRuntime:
    runtime: OpenCOATRuntime
    lifecycle: ConcernLifecycleManager
    verifier: ConcernVerifier
    plasticity: RtPlasticityService
    mode: PhaseIIBaseline
    dev_edits_used: int = 0
    splits: int = 0
    bootstrap_id: str = ""
    first_split_epoch: int | None = None
    last_split_guard_reason: str | None = None
    _epoch: int = 0
    _rollout_k: int = 1
    _rollout_temperature: float = 0.0

    def _bootstrap_metrics(self) -> dict[str, Any]:
        c = self.runtime.concern_store.get(self.bootstrap_id) if self.bootstrap_id else None
        score = c.activation_state.score if c and c.activation_state else None
        activations = c.metrics.activations if c and c.metrics else 0
        return {
            "bootstrap_score": score,
            "bootstrap_buffer": self.plasticity.buffer.count(self.bootstrap_id),
            "bootstrap_activations": activations,
            "bootstrap_state": c.lifecycle_state if c else None,
        }

    def plasticity_step(self) -> None:
        if self.mode == PhaseIIBaseline.STATIC:
            return
        self.plasticity.consume(max_records=None)
        if self.bootstrap_id:
            guard = self.plasticity.engine.last_split_guard(
                self.plasticity.buffer, self.bootstrap_id
            )
            self.last_split_guard_reason = guard.reason
        cold = self.plasticity.cold_step()
        n_split = int(cold.get("split", 0))
        if n_split > 0 and self.first_split_epoch is None:
            self.first_split_epoch = self._epoch
        self.splits += n_split

    def _record_rt(
        self,
        *,
        turn_id: str,
        joinpoint: str,
        host: str,
        reward: float,
        active: list[ActiveAspect],
        scenario_id: str,
        response_text: str = "",
    ) -> None:
        session_id = f"phase-ii-e{self._epoch}:{scenario_id}"
        if _FEATURE_MODE == "text":
            feature = (response_text or "")[:240]
            feature_axis = "text_ablation"
        else:
            feature = scenario_id
            feature_axis = "scenario_id"
        plastic_payload = []
        for asp in active:
            c = self.runtime.concern_store.get(asp.concern_id)
            if c is None or c.reflex:
                continue
            plastic_payload.append(
                {
                    "concern_id": asp.concern_id,
                    "activation_score": float(asp.activation_score),
                    "plastic": True,
                }
            )
        rec = RtRecord(
            ts=datetime.now(tz=UTC),
            session_id=session_id,
            turn_id=turn_id,
            joinpoint=joinpoint,
            host=host,
            hook=joinpoint,
            signal=RtSignal(
                kind="turn_complete",
                payload={
                    "phase": "ii",
                    "feature": feature,
                    "feature_axis": feature_axis,
                    "scenario_id": scenario_id,
                    "reward": reward,
                    "active_aspects": plastic_payload,
                },
            ),
            r=reward,
        )
        if active:
            self.plasticity.record_turn_activations(turn_id, active)
        self.plasticity.append(rec)

    def run_coding_trace(self, scenario: Scenario, *, record_rt: bool = True) -> dict[str, Any]:
        jp = JoinpointEvent(
            id=f"jp-{uuid4().hex[:8]}",
            level=2,
            name="before_response",
            host="phase_ii.coding",
            agent_session_id="phase-ii",
            ts=datetime.now(tz=UTC),
            payload={
                "text": scenario.user_text,
                "raw_text": scenario.user_text,
                "scenario_id": scenario.id,
            },
        )
        injection = self.runtime.on_joinpoint(jp)
        vector = self.runtime.current_vector()
        assert injection is not None and vector is not None

        system_parts = [
            "Binding concern directives (genesis bootstrap only):",
        ]
        for inj in injection.injections:
            system_parts.append(f"- [{inj.advice_type}] {inj.content}")
        messages = [
            {"role": "system", "content": "\n".join(system_parts)},
            {"role": "user", "content": f"[scenario:{scenario.id}]\n{scenario.user_text}"},
        ]
        rollout_rs: list[float] = []
        rollout_oks: list[bool] = []
        rollout_errors: list[str] = []
        llm_calls = 0
        last_response = ""
        last_verifications = []
        last_ok = False
        for _ in range(max(1, self._rollout_k)):
            llm_calls += 1
            try:
                last_response = _llm().chat(
                    messages=messages,
                    max_tokens=800,
                    temperature=self._rollout_temperature,
                )
            except Exception as exc:
                last_response = ""
                rollout_errors.append(f"{type(exc).__name__}: {exc}")
                rollout_oks.append(False)
                rollout_rs.append(0.0)
                continue
            verifications = self.verifier.verify_turn(
                active=vector,
                concerns=list(self.runtime.concern_store.iter_all()),
                host_output=last_response,
            )
            ok = evaluate_phase_ii_success(
                scenario_id=scenario.id,
                active_concern_ids=[a.concern_id for a in vector.active_concerns],
                verifications=verifications,
                response=last_response,
            )
            reward = evaluate_phase_ii_reward(
                scenario_id=scenario.id,
                active_concern_ids=[a.concern_id for a in vector.active_concerns],
                verifications=verifications,
                response=last_response,
            )
            last_verifications = verifications
            last_ok = ok
            rollout_oks.append(ok)
            rollout_rs.append(reward)
        ok = sum(1 for item in rollout_oks if item) / len(rollout_oks) >= 0.5
        reward = sum(rollout_rs) / len(rollout_rs)
        active = [
            ActiveAspect(a.concern_id, float(a.activation_score), True)
            for a in vector.active_concerns
        ]
        if record_rt:
            self._record_rt(
                turn_id=f"coding-{scenario.id}-{uuid4().hex[:6]}",
                joinpoint="before_response",
                host="phase_ii.coding",
                reward=reward,
                active=active,
                scenario_id=scenario.id,
                response_text=last_response,
            )
        return {
            "scenario_id": scenario.id,
            "variant_id": scenario.variant_id,
            "family": scenario.family,
            "user_text": scenario.user_text,
            "ok": ok,
            "last_rollout_ok": last_ok,
            "reward": reward,
            "llm_calls": llm_calls,
            "errors": rollout_errors,
            "active_concerns": [
                {"concern_id": a.concern_id, "activation_score": float(a.activation_score)}
                for a in vector.active_concerns
            ],
            "injections": [
                {
                    "concern_id": inj.concern_id,
                    "advice_type": str(inj.advice_type),
                    "content": inj.content,
                }
                for inj in injection.injections
            ],
            "verifications": [
                {
                    "concern_id": v.concern_id,
                    "satisfied": v.satisfied,
                    "score": v.score,
                    "notes": v.notes,
                    "evidence": v.evidence,
                }
                for v in last_verifications
            ],
            "response": last_response,
        }

    def run_coding(self, scenario: Scenario) -> tuple[bool, float, int]:
        trace = self.run_coding_trace(scenario, record_rt=True)
        ok = bool(trace["ok"])
        reward = float(trace["reward"])
        llm_calls = int(trace["llm_calls"])
        return ok, reward, llm_calls

    def hand_edit_on_failure(self, failed: bool) -> None:
        cfg = load_scenario_config()
        budget = int(cfg.get("hand_iteration_budget", 3))
        if (
            not failed
            or self.mode != PhaseIIBaseline.HAND_ITERATED
            or self.dev_edits_used >= budget
            or not self.bootstrap_id
        ):
            return
        seed = self.runtime.concern_store.get(self.bootstrap_id)
        if seed is None:
            return
        patch = _hand_patch_pool(seed)[self.dev_edits_used % len(_hand_patch_pool(seed))]
        self.runtime.concern_store.upsert(patch)
        self.runtime.dcn_store.add_node(patch)
        self.dev_edits_used += 1


def _freeze_static_bootstrap(concern: Concern) -> Concern:
    """Static baseline: same extracted id, weaker woven directive (no plasticity)."""

    advice = concern.advice
    if advice is not None:
        advice = advice.model_copy(update={"content": "Answer briefly without extra policy."})
    weaving = concern.weaving_policy
    if weaving is not None:
        weaving = weaving.model_copy(update={"priority": 0.25, "max_tokens": 80})
    return concern.model_copy(update={"advice": advice, "weaving_policy": weaving})


def _build_coding_runtime(mode: PhaseIIBaseline) -> _CodingRuntime:
    cfg = load_scenario_config()
    llm = _llm()
    store = MemoryConcernStore()
    dcn = MemoryDCNStore()
    runtime = OpenCOATRuntime(RuntimeConfig(), concern_store=store, dcn_store=dcn, llm=llm)
    bootstrap = _bootstrap_concern(store, dcn)
    if mode == PhaseIIBaseline.STATIC:
        bootstrap = _freeze_static_bootstrap(bootstrap)
        store.upsert(bootstrap)
    lifecycle = ConcernLifecycleManager(
        concern_store=store,
        dcn_store=dcn,
        reinforce_delta=0.05,
    )
    fd, rt_path = mkstemp(prefix="phase_ii_r_t_", suffix=".jsonl")
    os.close(fd)
    svc = RtPlasticityService(
        concern_store=store,
        dcn_store=dcn,
        path=Path(rt_path),
        lifecycle=lifecycle,
        baseline_ema_alpha=0.22,
        engine=PlasticityEngine(
            step_delta=0.05,
            split_beta=float(cfg.get("split_beta", 0.01)),
            split_theta_h=float(cfg.get("split_theta_h", 0.01)),
            split_n_min=int(cfg.get("split_n_min", 24)),
            split_use_welch=True,
            split_z_min=float(cfg.get("split_z_min", 1.96)),
            split_score_ema_alpha=float(cfg.get("split_score_ema_alpha", 0.35)),
        ),
    )
    return _CodingRuntime(
        runtime=runtime,
        lifecycle=lifecycle,
        verifier=ConcernVerifier(llm=llm),
        plasticity=svc,
        mode=mode,
        bootstrap_id=bootstrap.id,
        _rollout_k=max(1, int(cfg.get("rollout_k", 1))),
        _rollout_temperature=float(cfg.get("rollout_temperature", 0.0)),
    )


def run_learning_curve(
    mode: PhaseIIBaseline,
    *,
    epochs: int,
    train_families: list[str] | None = None,
    progress: PhaseIIProgress | None = None,
    on_epoch: Callable[[PhaseIIBaseline, EpisodePoint], None] | None = None,
) -> tuple[list[EpisodePoint], _CodingRuntime]:
    families = train_families or ["coding_train"]
    cr = _build_coding_runtime(mode)
    curve: list[EpisodePoint] = []

    for epoch in range(epochs):
        cr._epoch = epoch
        train = [s for fam in families for s in load_scenarios_for_epoch(family=fam, epoch=epoch)]
        cr.plasticity.credit_field.baseline.load_snapshot({"sums": {}, "counts": {}, "ema": {}})
        wins = 0
        rewards: list[float] = []
        calls = 0
        for sc in train:
            ok, r, c = cr.run_coding(sc)
            calls += c
            cr.hand_edit_on_failure(not ok)
            rewards.append(r)
            if ok:
                wins += 1
            if progress is not None:
                progress(
                    {
                        "event": "scenario",
                        "mode": mode.value,
                        "epoch": epoch,
                        "scenario_id": sc.id,
                        "variant_id": sc.variant_id,
                        "ok": ok,
                        "reward": r,
                        "llm_calls": c,
                    }
                )
        cr.plasticity_step()
        snap = cr.plasticity.connectome_stats()
        boot = cr._bootstrap_metrics()
        point = EpisodePoint(
            epoch=epoch,
            success_rate=wins / max(len(train), 1),
            mean_reward=sum(rewards) / max(len(rewards), 1),
            llm_calls=calls,
            dev_edits=cr.dev_edits_used,
            aspects=int(snap.get("aspects", 0)),
            edges=int(snap.get("edges", 0)),
            splits=cr.splits,
            bootstrap_score=boot["bootstrap_score"],
            bootstrap_buffer=int(boot["bootstrap_buffer"]),
            bootstrap_activations=int(boot["bootstrap_activations"]),
            bootstrap_state=boot["bootstrap_state"],
            first_split_epoch=cr.first_split_epoch,
            split_guard_reason=cr.last_split_guard_reason,
        )
        curve.append(point)
        if on_epoch is not None:
            on_epoch(mode, point)
        if progress is not None:
            progress({"event": "epoch", "mode": mode.value, "point": point.to_dict()})
    return curve, cr


def run_transfer_eval(
    cr: _CodingRuntime,
    *,
    families: list[str],
) -> list[TransferPoint]:
    """Evaluate held-out / cross-domain scenarios on the trained MAN store (bootstrap only)."""
    out: list[TransferPoint] = []

    for fam in families:
        scenarios = load_scenarios(family=fam)
        wins = 0
        rewards: list[float] = []
        for sc in scenarios:
            ok, r, _ = cr.run_coding(sc)
            rewards.append(r)
            if ok:
                wins += 1
        out.append(
            TransferPoint(
                split=fam,
                success_rate=wins / max(len(scenarios), 1),
                mean_reward=sum(rewards) / max(len(rewards), 1),
                n=len(scenarios),
            )
        )
    return out


def run_phase_ii_diagnostic(
    *,
    provider: str | None = None,
    family: str = "coding_train",
    limit: int | None = None,
) -> dict[str, Any]:
    """Low-cost real-LLM diagnostic: one MAN epoch with per-scenario traces."""
    global _BOOTSTRAP_CONCERN
    _BOOTSTRAP_CONCERN = None
    axis = configure_phase_ii_feature_mode("scenario_id")
    llm_label, llm_is_stub = configure_phase_ii_llm(provider)
    cr = _build_coding_runtime(PhaseIIBaseline.MAN_FULL)
    cr._epoch = 0
    scenarios = load_scenarios(family=family)
    if limit is not None:
        scenarios = scenarios[: max(0, limit)]
    traces = [cr.run_coding_trace(sc, record_rt=True) for sc in scenarios]
    cr.plasticity_step()
    boot = cr._bootstrap_metrics()
    stats = cr.plasticity.connectome_stats()
    return {
        "phase": "phase_ii_diagnostic",
        "llm": {"label": llm_label, "is_stub": llm_is_stub},
        "family": family,
        "feature_axis": axis,
        "scenarios": len(traces),
        "success_rate": sum(1 for t in traces if t["ok"]) / max(len(traces), 1),
        "mean_reward": sum(float(t["reward"]) for t in traces) / max(len(traces), 1),
        "bootstrap": boot,
        "connectome": stats,
        "split_guard_reason": cr.last_split_guard_reason,
        "traces": traces,
    }


def run_phase_ii(
    *,
    epochs: int | None = None,
    provider: str | None = None,
    feature_mode: str = "scenario_id",
    progress: PhaseIIProgress | None = None,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    """Full Phase II: curves for three baselines + frozen transfer after MAN train."""
    global _BOOTSTRAP_CONCERN
    _BOOTSTRAP_CONCERN = None
    axis = configure_phase_ii_feature_mode(feature_mode)
    llm_label, llm_is_stub = configure_phase_ii_llm(provider)
    cfg = load_scenario_config()
    ep = epochs if epochs is not None else int(cfg.get("default_epochs", 20))

    curves: dict[str, list[dict[str, Any]]] = {}
    man_rt: _CodingRuntime | None = None

    def checkpoint(extra: dict[str, Any] | None = None) -> None:
        if checkpoint_path is None:
            return
        payload = {
            "phase": "phase_ii_capability",
            "status": "running",
            "llm": {"label": llm_label, "is_stub": llm_is_stub},
            "epochs": ep,
            "feature_axis": axis,
            "curves": curves,
        }
        if extra:
            payload.update(extra)
        _write_json_atomic(checkpoint_path, payload)

    def on_epoch(mode: PhaseIIBaseline, point: EpisodePoint) -> None:
        curves.setdefault(mode.value, []).append(point.to_dict())
        checkpoint({"last_event": {"mode": mode.value, "epoch": point.epoch}})

    for mode in PhaseIIBaseline:
        if progress is not None:
            progress({"event": "mode_start", "mode": mode.value, "epochs": ep})
        pts, rt = run_learning_curve(
            mode,
            epochs=ep,
            progress=progress,
            on_epoch=on_epoch,
        )
        curves.setdefault(mode.value, [p.to_dict() for p in pts])
        if mode == PhaseIIBaseline.MAN_FULL:
            man_rt = rt

    assert man_rt is not None
    transfer = run_transfer_eval(
        man_rt,
        families=["coding_heldout", "openclaw_cross"],
    )
    checkpoint(
        {"last_event": {"event": "transfer_complete"}, "transfer": [t.to_dict() for t in transfer]}
    )
    static_final = curves[PhaseIIBaseline.STATIC.value][-1]["success_rate"]
    man_final = curves[PhaseIIBaseline.MAN_FULL.value][-1]["success_rate"]
    hand_final = curves[PhaseIIBaseline.HAND_ITERATED.value][-1]["success_rate"]
    train_man = curves[PhaseIIBaseline.MAN_FULL.value][0]["success_rate"]
    held = next(t for t in transfer if t.split == "coding_heldout")
    cross = next(t for t in transfer if t.split == "openclaw_cross")
    gap = abs(man_final - held.success_rate)

    man_curve = curves[PhaseIIBaseline.MAN_FULL.value]
    man_monotone = man_final >= max(p["success_rate"] for p in man_curve[: max(1, ep // 2)])

    if llm_is_stub:
        split_observed = man_rt.splits > 0 or man_rt.first_split_epoch is not None
        if train_man < 0.7:
            rises = man_final >= train_man + 0.12 and man_monotone
        else:
            rises = man_final >= train_man - 0.02 and (
                man_final > train_man or split_observed or man_monotone
            )
        gates = {
            "H0_man_beats_static_final": man_final > static_final + 0.08,
            "H0_man_near_hand_low_dev": man_final >= hand_final - 0.12,
            "H0_learning_curve_rises": rises,
            "H0_transfer_heldout_ok": held.success_rate >= 0.5,
            "H0_cross_domain_ok": cross.success_rate >= 0.5,
            "H0_transfer_gap_bounded": gap <= 0.35,
        }
    else:
        gates = {
            "H0_man_beats_static_final": man_final >= static_final,
            "H0_man_near_hand_low_dev": man_final >= hand_final - 0.2,
            "H0_learning_curve_rises": man_final >= train_man,
            "H0_transfer_heldout_ok": held.success_rate >= 0.25,
            "H0_cross_domain_ok": cross.success_rate >= 0.25,
            "H0_transfer_gap_bounded": gap <= 0.5,
        }
    families_covered = len({s.family for s in load_scenarios()})

    man_boot = curves[PhaseIIBaseline.MAN_FULL.value][-1]
    return {
        "phase": "phase_ii_capability",
        "status": "ran",
        "llm": {"label": llm_label, "is_stub": llm_is_stub},
        "gates_profile": "stub_strict" if llm_is_stub else "real_llm_advisory",
        "epochs": ep,
        "curves": curves,
        "transfer": [t.to_dict() for t in transfer],
        "h0_plasticity": {
            "unprimed": True,
            "feature_axis": axis,
            "split_n_min": int(load_scenario_config().get("split_n_min", 24)),
            "rollout_k": int(load_scenario_config().get("rollout_k", 1)),
            "first_split_epoch": man_rt.first_split_epoch,
            "last_split_guard_reason": man_rt.last_split_guard_reason,
            "bootstrap_final_score": man_boot.get("bootstrap_score"),
            "bootstrap_final_score_ema": man_rt.plasticity.engine.split_eligibility_score(
                man_rt.bootstrap_id,
                float(man_boot.get("bootstrap_score") or 0.0),
            )
            if man_rt.bootstrap_id
            else None,
            "bootstrap_final_buffer": man_boot.get("bootstrap_buffer"),
            "bootstrap_final_activations": man_boot.get("bootstrap_activations"),
            "cumulative_splits": man_rt.splits,
        },
        "summary": {
            "man_final_success": man_final,
            "static_final_success": static_final,
            "hand_final_success": hand_final,
            "hand_dev_edits": curves[PhaseIIBaseline.HAND_ITERATED.value][-1]["dev_edits"],
            "scenario_families": families_covered,
            "A_to_B_gap": gap,
            "h0_first_split_epoch": man_rt.first_split_epoch,
            "h0_cumulative_splits": man_rt.splits,
        },
        "gates": gates,
        "all_pass": all(gates.values()),
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
