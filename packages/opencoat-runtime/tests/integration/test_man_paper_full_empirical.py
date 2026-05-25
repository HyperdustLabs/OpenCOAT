"""MAN paper §8 Phase I: subprocess run.py + internal validity gates."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / "experiments" / "man_paper" / "run.py"
GEN = ROOT / "scripts" / "generate_morphogenetic_validation_data.py"


@pytest.fixture(scope="module", autouse=True)
def _fixtures_and_report(tmp_path_factory) -> Path:
    subprocess.run(
        [sys.executable, str(GEN)],
        check=True,
        cwd=ROOT,
    )
    out = tmp_path_factory.mktemp("man_paper") / "results"
    proc = subprocess.run(
        [sys.executable, str(RUN), "--output", str(out), "--epochs", "4"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return out / "report.json"


def test_phase_i_internal_validity_pass(_fixtures_and_report: Path) -> None:
    data = json.loads(_fixtures_and_report.read_text(encoding="utf-8"))
    iv = data.get("raw", {}).get("internal_validity", {})
    assert iv.get("all_pass") is True, iv.get("gates")
    failed = [k for k, v in iv.get("gates", {}).items() if not v]
    assert not failed, f"Phase I failed: {failed}"


def test_h1_man_efficiency_improves(_fixtures_and_report: Path) -> None:
    h1 = json.loads(_fixtures_and_report.read_text())["hypotheses"]["H1_efficiency"]
    assert h1["pass"] is True
    assert h1["delta_cps_man"] > 0


def test_auxiliary_man_beats_llm_optional(_fixtures_and_report: Path) -> None:
    data = json.loads(_fixtures_and_report.read_text(encoding="utf-8"))
    assert data["empirical_gates"].get("auxiliary_man_beats_llm") is not None
