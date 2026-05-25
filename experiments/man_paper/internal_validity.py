"""Paper §8 Phase I: internal validity (components work per spec).

H1--H5 are mechanism ablations; necessary but not sufficient for Phase II H0
(self-evolution capability). See ``phase_ii_protocol.py`` for the deferred H0
protocol; application-level proof is not claimed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from experiments.man_paper.ablations import (
    run_beta_sweep,
    run_h1_longitudinal,
    run_h2_reward_lift,
    run_h3_plasticity_ablation,
    run_h4_stochastic_sweep,
    run_h5_reflex_ablation,
    run_lambda_sweep,
)
from experiments.man_paper.phase_i_scale import load_scale, suite_label
from experiments.man_paper.suites import (
    ManMode,
    run_bandit_suite,
    run_h3_ablation,
    run_h4_proxy,
    run_replay_suite,
    run_soak_suite,
)


@dataclass
class HypothesisEvidence:
    id: str
    claim: str
    suite: str
    pass_: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim,
            "suite": self.suite,
            "pass": self.pass_,
            "metrics": self.metrics,
            "notes": self.notes,
        }


def evaluate_h1(*, epochs: int = 10, scale: dict | None = None) -> HypothesisEvidence:
    """H1: mature MAN lowers LLM-calls/success without losing success."""
    sc = scale or load_scale()
    trials = int(sc.get("h1_trials_per_epoch", 60))
    h1 = run_h1_longitudinal(epochs=epochs, trials_per_epoch=trials)
    labels = suite_label(sc)
    man = h1["series"][ManMode.MAN_FULL.value]
    static = h1["series"][ManMode.STATIC.value]
    man_cps0, man_cps1 = man[0]["llm_calls_per_success"], man[-1]["llm_calls_per_success"]
    man_sr_ok = man[-1]["success_rate"] >= man[0]["success_rate"] - 0.05
    static_flat = static[0]["llm_calls_per_success"] == static[-1]["llm_calls_per_success"]
    ok = bool(h1.get("pass")) and man_sr_ok and man_cps1 < man_cps0 and static_flat
    return HypothesisEvidence(
        id="H1",
        claim="LLM calls/success decreases as structure matures; success not degraded",
        suite=labels["H1"],
        pass_=ok,
        metrics={
            "man_cps_epoch0": man_cps0,
            "man_cps_final": man_cps1,
            "man_success_final": man[-1]["success_rate"],
            "static_cps": static[-1]["llm_calls_per_success"],
            "delta_cps_man": h1.get("delta_cps_man"),
        },
        notes=(
            "CPS from planner + verifier weight 1−score/0.65; guard_score is "
            "lifecycle.reinforce per success (warm step_delta≈0, no synthetic ramp)"
        ),
    )


def evaluate_h2(*, scale: dict | None = None) -> HypothesisEvidence:
    """H2: accepted split lowers child variance; bandit partition improves mean reward."""
    labels = suite_label(scale or load_scale())
    bimodal = run_bandit_suite(ManMode.MAN_FULL)
    lift = run_h2_reward_lift()
    ok = bimodal.success_rate == 1.0 and lift.success_rate == 1.0
    return HypothesisEvidence(
        id="H2",
        claim="Split reduces within-child reward variance; partition improves sub-context reward",
        suite=labels["H2"],
        pass_=ok,
        metrics={
            "bimodal_notes": bimodal.notes,
            "bandit_lift_notes": lift.notes,
            "bimodal_parent_var": 0.25,
        },
        notes=f"{bimodal.notes}; {lift.notes}",
    )


def evaluate_h3(*, scale: dict | None = None) -> HypothesisEvidence:
    """H3: tier-1 ρ necessary — spread + tier-1 splits under noise where uniform does not."""
    labels = suite_label(scale or load_scale())
    rho_t1, _rho_uni = run_h3_ablation()
    pl_t1, pl_uni = run_h3_plasticity_ablation()
    rho_spread = float(rho_t1.spurious_split_rate or 0)
    tier1_splits = int(pl_t1.splits or 0)
    uniform_splits = int(pl_uni.splits or 0)
    ok = (
        rho_t1.success_rate == 1.0
        and rho_spread > 0.5
        and tier1_splits >= 1
        and uniform_splits == 0
    )
    return HypothesisEvidence(
        id="H3",
        claim="Responsibility-weighted ρ enables credit cleaning; uniform ρ blocks valid cold split on noisy bandit",
        suite=labels["H3"],
        pass_=ok,
        metrics={
            "rho_hard_minus_soft": rho_spread,
            "tier1_splits": tier1_splits,
            "uniform_splits": uniform_splits,
            "tier1_mean_reward": pl_t1.mean_reward,
            "uniform_mean_reward": pl_uni.mean_reward,
        },
        notes=f"{pl_t1.notes}; {pl_uni.notes}",
    )


def evaluate_h4() -> HypothesisEvidence:
    """H4: hard aspects more reliable and more creditable than soft."""
    proxy = run_h4_proxy()
    noise = run_h4_stochastic_sweep()
    noise_ok = sum(1 for p in noise if p.success) >= 2
    gap = float(proxy.reliability_gap or 0)
    ok = proxy.success_rate == 1.0 and gap > 0.4 and noise_ok
    return HypothesisEvidence(
        id="H4",
        claim="ρ_hard > ρ_soft; outcome variance gap favors hard under added noise",
        suite="synthetic tied activation + simulated outcome noise sweep",
        pass_=ok,
        metrics={
            "reliability_gap_rho": gap,
            "noise_sweep_pass_count": sum(1 for p in noise if p.success),
            "noise_sweep": [p.to_dict() for p in noise],
        },
        notes=proxy.notes or "",
    )


def evaluate_h5(*, scale: dict | None = None) -> HypothesisEvidence:
    """H5: long-horizon structural size and reward remain bounded; reflex core retained."""
    labels = suite_label(scale or load_scale())
    soak_man = run_soak_suite(ManMode.MAN_FULL)
    soak_static = run_soak_suite(ManMode.STATIC)
    reflex_on, reflex_off = run_h5_reflex_ablation(long=True)
    span_man = float(soak_man.struct_stability or 0)
    span_static = float(soak_static.struct_stability or 0)
    ok = (
        soak_man.success_rate == 1.0
        and soak_static.success_rate == 1.0
        and span_man <= 8
        and span_static <= 8
        and int(reflex_on.aspects or 0) >= int(reflex_off.aspects or 0)
        and reflex_on.notes
        and "stable=True" in (reflex_on.notes or "")
    )
    return HypothesisEvidence(
        id="H5",
        claim=(
            f"{labels['H5']}: edge span bounded; reflex-on retains reflex "
            "concerns vs reflex-off ablation"
        ),
        suite=f"{labels['H5']} + disable_reflex_core ablation",
        pass_=ok,
        metrics={
            "soak_edge_span_man": span_man,
            "soak_edge_span_static": span_static,
            "soak_edges_man": soak_man.edges,
            "reflex_on_aspects": reflex_on.aspects,
            "reflex_off_aspects": reflex_off.aspects,
        },
        notes=f"man {soak_man.notes}; reflex {reflex_on.notes} / {reflex_off.notes}",
    )


def evaluate_foundations(*, scale: dict | None = None) -> list[HypothesisEvidence]:
    """Tier-1 replay, conservation, λ/β sensitivity (supporting internal validity)."""
    labels = suite_label(scale or load_scale())
    replay = run_replay_suite()
    lam = run_lambda_sweep()
    beta = run_beta_sweep()
    lam_ok = all(p.success for p in lam)
    beta_ok = any(p.metric == 1.0 and p.success for p in beta[:2]) and any(
        p.metric == 0.0 for p in beta[2:]
    )
    return [
        HypothesisEvidence(
            id="F1_replay",
            claim="Tier-1 replay is deterministic with conserved κ",
            suite=labels["F1"],
            pass_=replay.success_rate == 1.0,
            metrics={
                "max_conservation_residual": replay.conservation_max_abs_residual,
                "replay_hash": replay.replay_hash,
            },
            notes=replay.notes or "",
        ),
        HypothesisEvidence(
            id="F2_lambda",
            claim="Eligibility λ accumulates trace mass without breaking conservation",
            suite="λ ∈ {0,0.25,…,1} on bimodal fixture",
            pass_=lam_ok,
            metrics={"points": [p.to_dict() for p in lam]},
            notes="",
        ),
        HypothesisEvidence(
            id="F3_beta",
            claim="ΔF split gate accepts low β, rejects high β on bimodal buffer",
            suite="β sweep on paper.bimodal-guard",
            pass_=beta_ok,
            metrics={"points": [p.to_dict() for p in beta]},
            notes="",
        ),
    ]


def run_internal_validity(*, h1_epochs: int | None = None) -> dict[str, Any]:
    """Evaluate all Phase-I hypotheses; return report dict."""
    scale = load_scale()
    epochs = h1_epochs if h1_epochs is not None else int(scale.get("h1_epochs_default", 20))
    hypotheses = [
        evaluate_h1(epochs=epochs, scale=scale),
        evaluate_h2(scale=scale),
        evaluate_h3(scale=scale),
        evaluate_h4(),
        evaluate_h5(scale=scale),
    ]
    foundations = evaluate_foundations(scale=scale)
    gates = {h.id: h.pass_ for h in hypotheses}
    gates.update({f.id: f.pass_ for f in foundations})
    all_pass = all(gates.values())
    return {
        "phase": "internal_validity",
        "all_pass": all_pass,
        "h1_epochs": epochs,
        "scale": scale,
        "hypotheses": [h.to_dict() for h in hypotheses],
        "foundations": [f.to_dict() for f in foundations],
        "gates": gates,
    }


__all__ = [
    "HypothesisEvidence",
    "evaluate_h1",
    "evaluate_h2",
    "evaluate_h3",
    "evaluate_h4",
    "evaluate_h5",
    "run_internal_validity",
]
