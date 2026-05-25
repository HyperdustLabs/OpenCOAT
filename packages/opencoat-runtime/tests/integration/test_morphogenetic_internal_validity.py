"""Phase I internal validity: one integration gate per §8 hypothesis H1–H5 + foundations."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "opencoat-runtime"))
FIX_SCRIPT = ROOT / "scripts/generate_morphogenetic_validation_data.py"


@pytest.fixture(scope="module", autouse=True)
def _fixtures() -> None:
    subprocess.run(
        [sys.executable, str(FIX_SCRIPT)],
        check=True,
        cwd=ROOT,
    )


def _iv(*, epochs: int = 4) -> dict:
    from experiments.man_paper.internal_validity import run_internal_validity

    return run_internal_validity(h1_epochs=epochs)


def test_internal_validity_all_pass() -> None:
    report = _iv(epochs=4)
    assert report["phase"] == "internal_validity"
    assert report["all_pass"] is True, json.dumps(report["gates"], indent=2)
    assert all(report["gates"][h["id"]] for h in report["hypotheses"])


@pytest.mark.parametrize("hid", ["H1", "H2", "H3", "H4", "H5"])
def test_hypothesis_gate(hid: str) -> None:
    report = _iv(epochs=4)
    by_id = {h["id"]: h for h in report["hypotheses"]}
    assert by_id[hid]["pass"], by_id[hid]


def test_foundations_replay_conservation() -> None:
    report = _iv(epochs=4)
    f1 = next(f for f in report["foundations"] if f["id"] == "F1_replay")
    assert f1["pass"]
    assert f1["metrics"]["max_conservation_residual"] < 1e-5
