"""Emit LaTeX table fragments from experiment report.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _fmt(v: Any) -> str:
    if v is None:
        return "---"
    if isinstance(v, float):
        if abs(v) < 0.001 and v != 0:
            return f"{v:.2e}"
        return f"{v:.2f}"
    return str(v)


def main_table_tex(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{center}",
        r"\begin{tabular}{@{}lcccc@{}}",
        r"\toprule",
        r"Method & Success $\uparrow$ & LLM calls/succ.\ $\downarrow$ & Reliability gap & Struct.\ stability \\",
        r"\midrule",
    ]
    labels = {
        "llm_only": "LLM-only",
        "fixed_hand_prompt": "Fixed hand prompt",
        "static_aspect_graph": "Static aspect graph",
        "weight_only_plasticity": "Weight-only plasticity",
        "man_full": r"\textbf{MAN (full)}",
    }
    for row in rows:
        method = labels.get(row["method"], row["method"])
        lines.append(
            f"{method} & {_fmt(row.get('success_rate'))} & "
            f"{_fmt(row.get('llm_calls_per_success'))} & "
            f"{_fmt(row.get('reliability_gap'))} & "
            f"{_fmt(row.get('struct_stability'))} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{center}"])
    return "\n".join(lines)


def sweep_tex(points: list[dict[str, Any]], *, param_label: str) -> str:
    lines = [
        r"\begin{center}",
        r"\begin{tabular}{@{}lcc@{}}",
        r"\toprule",
        f"{param_label} & metric & pass \\\\",
        r"\midrule",
    ]
    for p in points:
        lines.append(
            f"{_fmt(p.get('value'))} & {_fmt(p.get('metric'))} & "
            f"{'yes' if p.get('success') else 'no'} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{center}"])
    return "\n".join(lines)


def write_tables(report_path: Path, out_dir: Path) -> None:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "main_table.tex").write_text(
        main_table_tex(data.get("main_table", [])), encoding="utf-8"
    )
    sweeps = data.get("sweeps", {})
    if "lambda" in sweeps:
        (out_dir / "lambda_sweep.tex").write_text(
            sweep_tex(sweeps["lambda"], param_label=r"$\lambda$"),
            encoding="utf-8",
        )
    if "beta" in sweeps:
        (out_dir / "beta_sweep.tex").write_text(
            sweep_tex(sweeps["beta"], param_label=r"$\beta$"),
            encoding="utf-8",
        )
    if "h4_noise" in sweeps:
        (out_dir / "h4_noise_sweep.tex").write_text(
            sweep_tex(sweeps["h4_noise"], param_label="noise"),
            encoding="utf-8",
        )
