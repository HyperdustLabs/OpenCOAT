#!/usr/bin/env python3
"""Run Phase II (H0) application experiments."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "opencoat-runtime"))

from experiments.man_paper.phase_ii_runner import run_phase_ii  # noqa: E402


def _write_curves_csv(path: Path, curves: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "mode",
                "epoch",
                "success_rate",
                "mean_reward",
                "llm_calls",
                "dev_edits",
                "aspects",
                "edges",
                "splits",
                "bootstrap_score",
                "bootstrap_buffer",
                "bootstrap_activations",
                "bootstrap_state",
                "first_split_epoch",
                "split_guard_reason",
            ],
        )
        w.writeheader()
        for mode, rows in curves.items():
            for row in rows:
                w.writerow({"mode": mode, **row})


def _write_results_md(path: Path, report: dict) -> None:
    s = report["summary"]
    llm = report.get("llm", {})
    lines = [
        "# Phase II results (H0 application)",
        "",
        f"**LLM:** `{llm.get('label', '?')}` (stub={llm.get('is_stub')})",
        f"**Gates profile:** {report.get('gates_profile', '')}",
        f"**All gates pass:** {report['all_pass']}",
        f"**Epochs:** {report['epochs']} (no mid-run code edits on MAN/static)",
        "",
        "## Learning curves (final epoch)",
        "",
        "| Mode | Success | Dev edits | Aspects | Splits |",
        "| --- | --- | --- | --- | --- |",
    ]
    for mode in ("man_full", "static_aspect_graph", "hand_iterated"):
        row = report["curves"][mode][-1]
        lines.append(
            f"| {mode} | {row['success_rate']:.2f} | {row['dev_edits']} | "
            f"{row['aspects']} | {row['splits']} |"
        )
    lines.extend(
        [
            "",
            "## Transfer (MAN frozen after train)",
            "",
            "| Split | Success | n |",
            "| --- | --- | --- |",
        ]
    )
    for t in report["transfer"]:
        lines.append(f"| {t['split']} | {t['success_rate']:.2f} | {t['n']} |")
    lines.extend(
        [
            "",
            f"**A→B gap (MAN train vs held-out):** {s['A_to_B_gap']:.2f}",
            f"**Scenario families:** {s['scenario_families']}",
            "",
            "## Gates",
            "",
        ]
    )
    for k, v in report["gates"].items():
        lines.append(f"- **{k}**: {'PASS' if v else 'FAIL'}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="MAN paper Phase II (H0)")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "experiments" / "man_paper" / "results",
    )
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM: bai|openai|anthropic|azure|stub|auto (auto: BAI_API_KEY first, else coding demo ladder)",
    )
    parser.add_argument(
        "--strict-gates",
        action="store_true",
        help="Exit 1 if H0 gates fail (default: strict only for stub LLM)",
    )
    parser.add_argument(
        "--feature-mode",
        choices=("scenario_id", "text"),
        default="scenario_id",
        help="Buffer split axis: scenario_id (H0 default) or text (ablation: LLM output as feature).",
    )
    parser.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Suppress per-scenario / per-epoch progress logs.",
    )
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    def progress(event: dict) -> None:
        if args.quiet_progress:
            return
        kind = event.get("event")
        if kind == "scenario":
            print(
                "progress "
                f"mode={event['mode']} epoch={event['epoch']} "
                f"scenario={event['scenario_id']} variant={event['variant_id']} "
                f"ok={event['ok']} reward={event['reward']:.2f} calls={event['llm_calls']}",
                flush=True,
            )
        elif kind == "epoch":
            point = event["point"]
            print(
                "epoch "
                f"mode={event['mode']} epoch={point['epoch']} "
                f"success={point['success_rate']:.2f} reward={point['mean_reward']:.2f} "
                f"aspects={point['aspects']} splits={point['splits']} "
                f"guard={point['split_guard_reason']}",
                flush=True,
            )
        elif kind == "mode_start":
            print(f"mode_start mode={event['mode']} epochs={event['epochs']}", flush=True)

    report = run_phase_ii(
        epochs=args.epochs,
        provider=args.provider,
        feature_mode=args.feature_mode,
        progress=progress,
        checkpoint_path=out / "phase_ii_partial.json",
    )
    (out / "phase_ii_partial.json").write_text(
        json.dumps({**report, "status": "complete"}, indent=2),
        encoding="utf-8",
    )
    (out / "phase_ii_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_curves_csv(out / "phase_ii_learning_curves.csv", report["curves"])
    _write_results_md(out / "PHASE_II_RESULTS.md", report)

    print(f"Wrote {out / 'PHASE_II_RESULTS.md'}")
    print(f"Wrote {out / 'phase_ii_learning_curves.csv'}")
    failed = [k for k, v in report["gates"].items() if not v]
    llm_info = report.get("llm", {})
    is_stub = llm_info.get("is_stub", True)
    strict = args.strict_gates or is_stub
    print(f"LLM: {llm_info.get('label')} (stub={is_stub}, strict_gates={strict})")
    if failed:
        print(f"Gates FAIL: {', '.join(failed)}")
        if strict:
            return 1
        print("(advisory only — re-run with --strict-gates to enforce)")
    else:
        print("Phase II H0: all gates PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
