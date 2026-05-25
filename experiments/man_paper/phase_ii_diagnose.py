#!/usr/bin/env python3
"""Run a low-cost Phase II diagnostic and write per-scenario traces."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "opencoat-runtime"))

from experiments.man_paper.phase_ii_runner import run_phase_ii_diagnostic  # noqa: E402


def _write_md(path: Path, report: dict) -> None:
    lines = [
        "# Phase II diagnostic",
        "",
        f"**LLM:** `{report['llm']['label']}` (stub={report['llm']['is_stub']})",
        f"**Family:** `{report['family']}`",
        f"**Success rate:** {report['success_rate']:.2f}",
        f"**Mean reward:** {report['mean_reward']:.2f}",
        f"**Split guard:** {report.get('split_guard_reason')}",
        "",
        "## Scenarios",
        "",
        "| Scenario | OK | Reward | Active | Response excerpt |",
        "| --- | --- | --- | --- | --- |",
    ]
    for trace in report["traces"]:
        active = ",".join(a["concern_id"] for a in trace["active_concerns"]) or "-"
        excerpt = " ".join(str(trace["response"]).split())[:180].replace("|", "\\|")
        lines.append(
            f"| `{trace['scenario_id']}` | {trace['ok']} | "
            f"{float(trace['reward']):.2f} | `{active}` | {excerpt} |"
        )
    lines.extend(["", "## Full Responses", ""])
    for trace in report["traces"]:
        lines.extend(
            [
                f"### {trace['scenario_id']}",
                "",
                f"User: {trace['user_text']}",
                "",
                "```text",
                str(trace["response"]).strip(),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Low-cost Phase II H0 diagnostic")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--family", default="coding_train")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "experiments" / "man_paper" / "results" / "diagnostics",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = run_phase_ii_diagnostic(
        provider=args.provider,
        family=args.family,
        limit=args.limit,
    )
    stem = f"phase_ii_diagnostic_{report['llm']['label'].replace('/', '_')}_{args.family}"
    if args.limit is not None:
        stem += f"_n{args.limit}"
    json_path = args.output / f"{stem}.json"
    md_path = args.output / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_md(md_path, report)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(
        f"success_rate={report['success_rate']:.2f} "
        f"mean_reward={report['mean_reward']:.2f} "
        f"split_guard={report.get('split_guard_reason')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
