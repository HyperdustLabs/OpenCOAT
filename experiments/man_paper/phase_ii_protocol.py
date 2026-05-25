"""Paper §8 Phase II: H0 self-evolution capability harness.

Phase I (``internal_validity``) proves mechanisms H1--H5; passing Phase I is
necessary but not sufficient for H0. Phase II is the application-level H0
runner: clean genesis, MAN/static/hand baselines, learning curves, and frozen
transfer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PHASE_II_REPORT = ROOT / "experiments" / "man_paper" / "results" / "phase_ii_report.json"

# Mirrors morphogenetic-aspect-agent-paper.tex §8 Phase II subsection.
PHASE_II_PROTOCOL: dict[str, Any] = {
    "phase": "phase_ii_capability",
    "status": "implemented_h0_harness",
    "primary_hypothesis": {
        "id": "H0",
        "claim": (
            "Morphogenetic learning alone (zero code changes) raises competence on "
            "un-hand-built application scenarios; structure transfers to held-out "
            "and cross-domain settings."
        ),
        "relation_to_phase_i": (
            "H1--H5 are mechanism ablations; Phase I pass is necessary but not sufficient for H0."
        ),
    },
    "signatures": {
        "learning_curve": {
            "metric": "success_or_reward_vs_experience",
            "constraint": "no_developer_edits_mid_run",
            "interpretation": "rising curve from slow dynamics alone",
        },
        "transfer": {
            "train": "scenario_set_A",
            "eval": ["held_out_B", "cross_domain_>=1"],
            "surrogate_for_general": "small_A_to_B_gap_same_substrate_and_law",
        },
        "headline_baseline": {
            "name": "developer_effort_matched_hand_iterated",
            "comparison": (
                "MAN curve overtakes static graph and approaches hand-iterated "
                "agent at near-zero developer effort"
            ),
            "extends_phase_i_baselines": True,
        },
        "breadth_and_cost": {
            "coverage": "scenario_family_count",
            "cost_to_competence": "samples_or_compute_to_target_success",
        },
    },
    "scope": {
        "general_claim": "operationalized_not_literal",
        "target_environments": ["coding", "openclaw"],
    },
    "genesis": {
        "entrypoint": "experiments.man_paper.phase_ii_seed.seed_h0_graph",
        "cortex": "one intent_alignment concern from MAN_IDENTITY_PROMPT",
        "conserved_reflex": "h0.conserved.fail-closed",
        "initial_edges": 0,
        "forbidden_seeds": [
            "plugin seed_stores()",
            "SKILL.md concern upsert",
            "demo coding/OpenClaw presets",
        ],
    },
    "implemented_harness": {
        "entrypoint": "uv run python experiments/man_paper/phase_ii_run.py",
        "script": "bash scripts/run-man-paper-phase-ii.sh",
        "scenario_families": ["coding_train", "coding_heldout", "openclaw_cross"],
        "baselines": ["man_full", "static_aspect_graph", "hand_iterated"],
        "outputs": [
            "experiments/man_paper/results/PHASE_II_RESULTS.md",
            "experiments/man_paper/results/phase_ii_learning_curves.csv",
            "experiments/man_paper/results/phase_ii_report.json",
        ],
    },
    "clean_h0_constraints": {
        "no_split_gate_priming": True,
        "feature_axis_default": "scenario_id",
        "strict_stub_gates": True,
        "real_llm_gates": "advisory unless --strict-gates",
    },
    "phase_i_entrypoint": "bash scripts/run-man-paper-experiments.sh",
}


def _latest_phase_ii_result() -> dict[str, Any] | None:
    if not PHASE_II_REPORT.exists():
        return None
    try:
        data = json.loads(PHASE_II_REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    summary = data.get("summary") if isinstance(data, dict) else None
    h0 = data.get("h0_plasticity") if isinstance(data, dict) else None
    gates = data.get("gates") if isinstance(data, dict) else None
    if not isinstance(summary, dict) or not isinstance(h0, dict) or not isinstance(gates, dict):
        return None
    return {
        "path": str(PHASE_II_REPORT.relative_to(ROOT)),
        "all_pass": bool(data.get("all_pass")),
        "llm": data.get("llm", {}),
        "gates_profile": data.get("gates_profile"),
        "epochs": data.get("epochs"),
        "summary": summary,
        "h0_plasticity": h0,
        "failed_gates": [k for k, v in gates.items() if not v],
    }


def protocol_document() -> str:
    """Human-readable Phase II harness contract (for RESULTS / PHASE_II_PROTOCOL.md)."""
    p = PHASE_II_PROTOCOL
    h0 = p["primary_hypothesis"]
    harness = p["implemented_harness"]
    genesis = p["genesis"]
    latest = _latest_phase_ii_result()
    lines = [
        "# MAN paper — Phase II results (H0)",
        "",
        f"**Harness status:** {p['status']}",
        "",
        f"Run: `{harness['script']}` → `PHASE_II_RESULTS.md`.",
        "",
        "## H0 (primary)",
        "",
        h0["claim"],
        "",
        f"*{h0['relation_to_phase_i']}*",
        "",
        "## Signatures",
        "",
        "- **Learning curve:** success/reward vs experience; no developer edits mid-run.",
        "- **Transfer:** evolve on A; evaluate on held-out B and ≥1 cross-domain set;",
        "  small A→B gap = testable surrogate for general competence.",
        "- **Headline baseline:** developer-effort-matched hand-iterated agent;",
        "  MAN should beat static and approach hand-iterated at ~zero dev effort.",
        "- **Breadth & cost:** scenario-family coverage; cost-to-competence.",
        "",
        "## Implemented harness",
        "",
        f"- **Genesis:** `{genesis['entrypoint']}`.",
        f"- **Cortex:** {genesis['cortex']}.",
        f"- **Conserved reflex:** `{genesis['conserved_reflex']}`.",
        f"- **Initial edges:** {genesis['initial_edges']}.",
        f"- **Scenario families:** {', '.join(harness['scenario_families'])}.",
        f"- **Baselines:** {', '.join(harness['baselines'])}.",
        (
            "- **Clean H0:** no plugin seeds, no SKILL.md concern upsert, "
            "no demo presets, no split-gate priming."
        ),
        "",
        "## Outputs",
        "",
    ]
    for path in harness["outputs"]:
        lines.append(f"- `{path}`")
    lines.extend(
        [
            "",
            "## Latest result",
            "",
        ]
    )
    if latest is None:
        lines.append("No `phase_ii_report.json` found yet. Run the Phase II command above.")
    else:
        summary = latest["summary"]
        h0p = latest["h0_plasticity"]
        failed = latest["failed_gates"]
        lines.extend(
            [
                f"- **Report:** `{latest['path']}`",
                f"- **All gates pass:** {latest['all_pass']}",
                (
                    f"- **LLM:** `{latest.get('llm', {}).get('label', '?')}` "
                    f"(stub={latest.get('llm', {}).get('is_stub')})"
                ),
                f"- **Epochs:** {latest.get('epochs')}",
                f"- **MAN final success:** {summary.get('man_final_success')}",
                f"- **Static final success:** {summary.get('static_final_success')}",
                f"- **Hand final success:** {summary.get('hand_final_success')}",
                f"- **A→B gap:** {summary.get('A_to_B_gap')}",
                f"- **H0 unprimed:** {h0p.get('unprimed')}",
                f"- **Feature axis:** `{h0p.get('feature_axis')}`",
                f"- **Cumulative splits:** {h0p.get('cumulative_splits')}",
                f"- **Failed gates:** {', '.join(failed) if failed else 'none'}",
            ]
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            f"Target: {', '.join(p['scope']['target_environments'])}.",
            (
                "“General” is operationalized (diverse held-out + cross-domain + breadth), "
                "not literal."
            ),
            "",
            "## Phase I prerequisite",
            "",
            f"Run first: `{p['phase_i_entrypoint']}` → `INTERNAL_VALIDITY.md`.",
        ]
    )
    return "\n".join(lines)


def run_phase_ii_protocol() -> dict[str, Any]:
    """Return the implemented harness contract plus latest result when present."""
    out = dict(PHASE_II_PROTOCOL)
    latest = _latest_phase_ii_result()
    if latest is not None:
        out["latest_result"] = latest
    return out


__all__ = ["PHASE_II_PROTOCOL", "protocol_document", "run_phase_ii_protocol"]
