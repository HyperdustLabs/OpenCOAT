"""Build readable Phase I reports: scale table, pitfalls, H1 CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def pitfalls_markdown() -> str:
    return "\n".join(
        [
            "## How to read these numbers (common pitfalls)",
            "",
            "1. **`llm_calls_per_success` (H1) is not API token usage.** The harness counts",
            "   planner + fractional verifier weight from **real** `concern.score`",
            "   (`lifecycle.reinforce` per successful trial; warm step_delta≈0).",
            "",
            "2. **The auxiliary main table (`RESULTS.md`) is a tiny demo loop (~40 turns).**",
            "   Do not use it for effect sizes; use `h1_longitudinal.csv` and hypothesis metrics in",
            "   `internal_validity.json`.",
            "",
            "3. **H3 reports split counts (often 1 vs 0), not a large spurious-split rate study.**",
            "   It checks that tier-1 ρ enables a valid cold split on the noisy bandit while uniform ρ does not.",
            "",
            "4. **H5 soak measures bounded span on repeated bimodal replay, not growing competence.**",
            "   Small aspect/edge counts are expected; Phase II (H0) owns learning curves on real scenarios.",
            "",
        ]
    )


def scale_table_markdown(scale: dict[str, Any]) -> str:
    profile = scale.get("profile", "unknown")
    lines = [
        "## Data scale (current profile)",
        "",
        f"Profile: **`{profile}`** (see `fixtures/morphogenetic/scale.json`).",
        "",
        "| Artifact | Rows / scale | Role |",
        "| --- | --- | --- |",
        f"| `r_t_bimodal.jsonl` | {scale.get('bimodal_rows', '?')} | H2 variance, F1 replay, F3 β |",
        f"| `r_t_bandit.jsonl` | {scale.get('bandit_rows', '?')} | H2 lift, H3 tier-1 plasticity |",
        f"| `r_t_bandit_noisy.jsonl` | {scale.get('bandit_noisy_rows', '?')} | H3 uniform-ρ stress |",
        f"| `r_t_soak_long.jsonl` | {scale.get('soak_rows', '?')} "
        f"({scale.get('soak_repeats', '?')}× bimodal) | H5 bounded soak |",
        f"| H1 longitudinal | {scale.get('h1_epochs_default', '?')} epochs × "
        f"{scale.get('h1_trials_per_epoch', '?')} trials | CPS proxy (not Phase II) |",
        "",
        "Phase I = mechanism smoke at this scale. **Not sufficient for H0** (see `PHASE_II_PROTOCOL.md`).",
        "",
    ]
    return "\n".join(lines)


def write_h1_longitudinal_csv(h1: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "mode",
                "epoch",
                "llm_calls_per_success",
                "success_rate",
                "guard_score",
                "mature",
            ],
        )
        w.writeheader()
        for mode, rows in h1.get("series", {}).items():
            for row in rows:
                w.writerow(
                    {
                        "mode": mode,
                        "epoch": int(row["epoch"]),
                        "llm_calls_per_success": f"{row['llm_calls_per_success']:.4f}",
                        "success_rate": f"{row['success_rate']:.4f}",
                        "guard_score": f"{row.get('guard_score', 0):.4f}",
                        "mature": int(row.get("mature", 0)),
                    }
                )


def h1_summary_markdown(h1: dict[str, Any]) -> str:
    lines = [
        "## H1 learning curve (symbolic CPS proxy)",
        "",
        "| mode | epoch0 CPS | final CPS | final guard_score | mature |",
        "| --- | --- | --- | --- | --- |",
    ]
    for mode, rows in sorted(h1.get("series", {}).items()):
        if not rows:
            continue
        gs = rows[-1].get("guard_score", 0.0)
        lines.append(
            f"| `{mode}` | {rows[0]['llm_calls_per_success']:.2f} | "
            f"{rows[-1]['llm_calls_per_success']:.2f} | {gs:.3f} | "
            f"{int(rows[-1].get('mature', 0))} |"
        )
    lines.extend(
        [
            "",
            "Full series: `h1_longitudinal.csv` (plot epoch vs `llm_calls_per_success`).",
            "",
        ]
    )
    return "\n".join(lines)


def hypothesis_detail_markdown(iv: dict[str, Any]) -> str:
    lines = ["## Hypothesis metrics (from last run)", ""]
    for h in iv.get("hypotheses", []):
        lines.append(f"### {h['id']} — {'PASS' if h['pass'] else 'FAIL'}")
        lines.append("")
        lines.append(f"- **Suite:** {h.get('suite', '')}")
        if h.get("notes"):
            lines.append(f"- **Note:** {h['notes']}")
        metrics = h.get("metrics") or {}
        if metrics:
            lines.append("- **Metrics:**")
            for k, v in metrics.items():
                if k == "noise_sweep":
                    continue
                lines.append(f"  - `{k}`: {v}")
        lines.append("")
    return "\n".join(lines)


def build_internal_validity_md(
    iv: dict[str, Any],
    *,
    h1: dict[str, Any],
    scale: dict[str, Any],
) -> str:
    parts = [
        "# MAN paper — Phase I internal validity (§8 H1–H5)",
        "",
        "Validates **components per spec** on preregistered fixtures. "
        "Regenerate: `bash scripts/run-man-paper-experiments.sh`.",
        "",
        f"**All pass:** {iv['all_pass']}",
        "",
        scale_table_markdown(scale),
        pitfalls_markdown(),
        "## Gates",
        "",
        "| ID | Pass | Claim (abbrev.) |",
        "| --- | --- | --- |",
    ]
    for h in iv["hypotheses"]:
        claim = (h.get("claim") or "")[:72]
        parts.append(f"| {h['id']} | {'yes' if h['pass'] else '**no**'} | {claim} |")
    parts.extend(["", "## Foundations", ""])
    for f in iv["foundations"]:
        parts.append(f"- **{f['id']}**: {'PASS' if f['pass'] else 'FAIL'} — {f['claim']}")
    parts.append("")
    parts.append(h1_summary_markdown(h1))
    parts.append(hypothesis_detail_markdown(iv))
    return "\n".join(parts)


def attach_scale_to_iv(iv: dict[str, Any], scale: dict[str, Any]) -> dict[str, Any]:
    out = dict(iv)
    out["scale"] = scale
    return out
