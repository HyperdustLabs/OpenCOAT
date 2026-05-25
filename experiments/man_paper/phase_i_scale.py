"""Phase I fixture scale manifest and row counts (for readable reports)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "packages/opencoat-runtime/tests/fixtures/morphogenetic"
SCALE_JSON = FIXTURES / "scale.json"

# Default profile when scale.json missing (legacy 96/256).
STANDARD = {
    "profile": "standard",
    "bimodal_rows": 32,
    "bandit_rows": 96,
    "bandit_noisy_rows": 96,
    "soak_rows": 256,
    "soak_repeats": 8,
    "h1_epochs_default": 20,
    "h1_trials_per_epoch": 60,
}

STRESS = {
    "profile": "stress",
    "bimodal_rows": 32,
    "bandit_rows": 384,
    "bandit_noisy_rows": 384,
    "soak_rows": 1024,
    "soak_repeats": 32,
    "h1_epochs_default": 20,
    "h1_trials_per_epoch": 60,
}


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def load_scale() -> dict[str, Any]:
    """Read generator-written manifest, else infer from files."""
    if SCALE_JSON.exists():
        data = json.loads(SCALE_JSON.read_text(encoding="utf-8"))
        return {**STANDARD, **data}
    return {
        **STANDARD,
        "bimodal_rows": _count_jsonl(FIXTURES / "r_t_bimodal.jsonl"),
        "bandit_rows": _count_jsonl(FIXTURES / "r_t_bandit.jsonl"),
        "bandit_noisy_rows": _count_jsonl(FIXTURES / "r_t_bandit_noisy.jsonl"),
        "soak_rows": _count_jsonl(FIXTURES / "r_t_soak_long.jsonl"),
    }


def suite_label(scale: dict[str, Any]) -> dict[str, str]:
    """Human-readable suite strings keyed by hypothesis."""
    b = int(scale.get("bimodal_rows", 32))
    band = int(scale.get("bandit_rows", 96))
    soak = int(scale.get("soak_rows", 256))
    ep = int(scale.get("h1_epochs_default", 20))
    trials = int(scale.get("h1_trials_per_epoch", 60))
    return {
        "H1": f"demo-tool-block, {ep} epochs × {trials} trials (kernel+lifecycle score)",
        "H2": f"r_t_bimodal.jsonl ({b}) + r_t_bandit.jsonl ({band}), ΔF guards",
        "H3": f"ρ pair + bandit ({band}) vs bandit_noisy ({scale.get('bandit_noisy_rows', band)})",
        "H5": f"r_t_soak_long.jsonl ({soak} rows)",
        "F1": f"r_t_bimodal.jsonl ({b}) ×2 cold replay",
    }
