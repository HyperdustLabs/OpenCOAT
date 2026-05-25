#!/usr/bin/env python3
"""Run MAN paper §8: Phase I internal validity (H1–H5) + auxiliary tables."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "opencoat-runtime"))

from experiments.man_paper.ablations import (  # noqa: E402
    run_beta_sweep,
    run_h1_longitudinal,
    run_h2_reward_lift,
    run_h3_plasticity_ablation,
    run_h4_stochastic_sweep,
    run_h5_reflex_ablation,
    run_lambda_sweep,
    run_tier2_ablation,
)
from experiments.man_paper.internal_validity import run_internal_validity  # noqa: E402
from experiments.man_paper.metrics import ExperimentReport, RunMetrics  # noqa: E402
from experiments.man_paper.phase_i_readme import (  # noqa: E402
    build_internal_validity_md,
    write_h1_longitudinal_csv,
)
from experiments.man_paper.phase_i_scale import load_scale  # noqa: E402
from experiments.man_paper.phase_ii_protocol import (  # noqa: E402
    protocol_document,
    run_phase_ii_protocol,
)
from experiments.man_paper.suites import (  # noqa: E402
    ManMode,
    _demo_tool_block_concern,
    run_bandit_suite,
    run_demo_tool_suite,
    run_h3_ablation,
    run_h4_proxy,
    run_replay_suite,
    run_soak_suite,
)
from experiments.man_paper.tex_sync import write_tables  # noqa: E402


def _markdown_table(rows: list[RunMetrics], *, columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, sep]
    for r in rows:
        cells = []
        for col in columns:
            val = getattr(r, col, None)
            if val is None:
                cells.append("—")
            elif isinstance(val, float):
                cells.append(f"{val:.3f}")
            else:
                cells.append(str(val))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _rpc(url: str, method: str, params: dict[str, object]) -> dict[str, object]:
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def check_live_daemon(url: str) -> dict[str, object]:
    try:
        ping = _rpc(url, "health.ping", {})
        demo: dict[str, object] = {"ping": ping.get("result", ping)}
        concern = _demo_tool_block_concern().model_dump(mode="json")
        up = _rpc(url, "concern.upsert", {"concern": concern})
        demo["concern_upsert"] = up.get("result", up)
        for cmd, want_allow in (("rm -rf /tmp/paper", False), ("ls -la", True)):
            out = _rpc(
                url,
                "effector.run_turn",
                {
                    "joinpoint": {
                        "id": "jp-live",
                        "level": 3,
                        "name": "before_tool_call",
                        "host": "paper-exp",
                        "ts": "2026-05-19T12:00:00+00:00",
                    },
                    "action": {
                        "kind": "tool_call",
                        "name": "shell.exec",
                        "args": {"command": cmd},
                    },
                    "context": {"command": cmd},
                    "turn_id": f"live-{cmd[:8]}",
                },
            )
            allowed = (out.get("result") or {}).get("allowed")
            demo[cmd] = {
                "allowed": allowed,
                "expect_allow": want_allow,
                "ok": allowed == want_allow,
            }
        demo["demo_ok"] = all(
            v.get("ok") for v in demo.values() if isinstance(v, dict) and "ok" in v
        )
        return demo
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="MAN paper §8 Phase I internal validity")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "experiments" / "man_paper" / "results",
    )
    parser.add_argument("--live-rpc", default="http://127.0.0.1:7878/rpc")
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="H1 longitudinal epochs (default: scale.json h1_epochs_default)",
    )
    args = parser.parse_args()
    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    scale = load_scale()
    h1_epochs = args.epochs if args.epochs is not None else int(scale.get("h1_epochs_default", 20))
    iv = run_internal_validity(h1_epochs=h1_epochs)
    phase_ii = run_phase_ii_protocol()

    report = ExperimentReport()
    report.raw["internal_validity"] = iv
    report.raw["phase_ii_protocol"] = phase_ii

    report.main_table = [
        run_demo_tool_suite(ManMode.LLM_ONLY),
        run_demo_tool_suite(ManMode.FIXED_PROMPT),
        run_demo_tool_suite(ManMode.STATIC),
        run_demo_tool_suite(ManMode.WEIGHT_ONLY),
        run_demo_tool_suite(ManMode.MAN_FULL),
    ]

    h1 = run_h1_longitudinal(
        epochs=h1_epochs,
        trials_per_epoch=int(scale.get("h1_trials_per_epoch", 60)),
    )
    tier1_rho, uniform_rho = run_h3_ablation()
    h3_plast_tier1, h3_plast_uni = run_h3_plasticity_ablation()
    reflex_on, reflex_off = run_h5_reflex_ablation(long=True)
    h2_lift = run_h2_reward_lift()

    report.sweeps = {
        "lambda": [p.to_dict() for p in run_lambda_sweep()],
        "beta": [p.to_dict() for p in run_beta_sweep()],
        "h4_noise": [p.to_dict() for p in run_h4_stochastic_sweep()],
    }

    report.ablation_table = [
        RunMetrics(
            method="-- responsibility ρ (H3)",
            success_rate=tier1_rho.success_rate,
            llm_calls_per_success=1.0,
            spurious_split_rate=tier1_rho.spurious_split_rate,
            notes=tier1_rho.notes,
        ),
        RunMetrics(
            method="-- responsibility plasticity (H3)",
            success_rate=h3_plast_tier1.success_rate,
            llm_calls_per_success=1.0,
            spurious_split_rate=h3_plast_uni.spurious_split_rate
            - h3_plast_tier1.spurious_split_rate,
            notes=f"tier1 {h3_plast_tier1.notes}; uniform {h3_plast_uni.notes}",
        ),
        run_replay_suite(),
        run_h4_proxy(),
        run_tier2_ablation(),
        RunMetrics(
            method="-- conserved reflex (H5)",
            success_rate=reflex_on.success_rate - reflex_off.success_rate,
            llm_calls_per_success=1.0,
            spurious_split_rate=reflex_off.struct_stability,
            notes=f"on {reflex_on.notes}; off {reflex_off.notes}",
        ),
        h2_lift,
    ]

    report.hypotheses = {
        "H1_efficiency": h1,
        "H2_differentiation": {
            "bimodal": run_bandit_suite(ManMode.MAN_FULL).to_dict(),
            "bandit_lift": h2_lift.to_dict(),
        },
        "H3_credit_necessity": {
            "rho_tier1": tier1_rho.to_dict(),
            "rho_uniform": uniform_rho.to_dict(),
            "plasticity_tier1": h3_plast_tier1.to_dict(),
            "plasticity_uniform": h3_plast_uni.to_dict(),
        },
        "H4_hard_gt_soft": {
            "rho_proxy": run_h4_proxy().to_dict(),
            "noise_sweep": report.sweeps["h4_noise"],
        },
        "H5_bounded": {
            "soak_man": run_soak_suite(ManMode.MAN_FULL).to_dict(),
            "soak_static": run_soak_suite(ManMode.STATIC).to_dict(),
            "reflex_on": reflex_on.to_dict(),
            "reflex_off": reflex_off.to_dict(),
        },
    }

    report.empirical_gates = dict(iv["gates"])
    report.empirical_gates["auxiliary_man_beats_llm"] = (
        report.main_table[-1].success_rate > report.main_table[0].success_rate
    )

    report.raw["live_daemon"] = check_live_daemon(args.live_rpc)

    report_path = out_dir / "report.json"
    report_path.write_text(report.to_json(), encoding="utf-8")
    write_tables(report_path, out_dir / "latex")

    (out_dir / "INTERNAL_VALIDITY.md").write_text(
        build_internal_validity_md(iv, h1=h1, scale=scale),
        encoding="utf-8",
    )
    write_h1_longitudinal_csv(h1, out_dir / "h1_longitudinal.csv")
    (out_dir / "internal_validity.json").write_text(
        json.dumps(iv, indent=2),
        encoding="utf-8",
    )
    (out_dir / "PHASE_II_PROTOCOL.md").write_text(protocol_document(), encoding="utf-8")
    (out_dir / "phase_ii_protocol.json").write_text(
        json.dumps(phase_ii, indent=2),
        encoding="utf-8",
    )

    md = [
        "# MAN paper — auxiliary metrics & tables",
        "",
        f"H1 epochs: {h1_epochs} (profile `{scale.get('profile')}`). "
        "See `INTERNAL_VALIDITY.md` + `h1_longitudinal.csv`.",
        "",
        "## Phase I gates",
        "",
    ]
    for k, v in iv["gates"].items():
        md.append(f"- **{k}**: {'PASS' if v else 'FAIL'}")
    md.extend(
        [
            "",
            "## Main table",
            "",
            _markdown_table(
                report.main_table,
                columns=[
                    "method",
                    "success_rate",
                    "llm_calls_per_success",
                    "reliability_gap",
                    "struct_stability",
                ],
            ),
        ]
    )
    md.extend(["", "## H1 longitudinal (last epoch CPS)", ""])
    for mode, rows in h1.get("series", {}).items():
        if rows:
            md.append(
                f"- {mode}: {rows[-1]['llm_calls_per_success']:.2f} (epoch0={rows[0]['llm_calls_per_success']:.2f})"
            )

    md.extend(["", "## λ / β sweeps", ""])
    for name in ("lambda", "beta"):
        md.append(f"### {name}")
        for p in report.sweeps.get(name, []):
            md.append(f"- {p['value']}: metric={p['metric']:.4f} ({p['notes']})")

    md.extend(
        [
            "",
            "## Ablations",
            "",
            _markdown_table(
                report.ablation_table,
                columns=["method", "success_rate", "spurious_split_rate", "notes"],
            ),
        ]
    )

    if report.raw.get("live_daemon"):
        md.extend(
            [
                "",
                "## Live daemon",
                "```json",
                json.dumps(report.raw["live_daemon"], indent=2),
                "```",
            ]
        )

    (out_dir / "RESULTS.md").write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Wrote {out_dir / 'RESULTS.md'}")
    print(f"Wrote {out_dir / 'latex'}/")
    failed = [k for k, v in iv["gates"].items() if not v]
    print(f"Wrote {out_dir / 'INTERNAL_VALIDITY.md'}")
    print(f"Wrote {out_dir / 'h1_longitudinal.csv'}")
    print(f"Wrote {out_dir / 'PHASE_II_PROTOCOL.md'} (see run-man-paper-phase-ii.sh for H0)")
    if failed:
        print(f"Phase I FAIL: {', '.join(failed)}")
        return 1
    print("Phase I internal validity: all H1–H5 + foundations PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
