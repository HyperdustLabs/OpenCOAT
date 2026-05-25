"""Phase II H0 smoke (application scenarios, stub LLM)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "opencoat-runtime"))

_FORCE_STUB = {"OPENCOAT_PHASE_II_FORCE_STUB": "1"}


def test_phase_ii_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCOAT_PHASE_II_FORCE_STUB", "1")
    from experiments.man_paper.phase_ii_runner import run_phase_ii

    report = run_phase_ii(epochs=6, provider="stub")
    assert report["phase"] == "phase_ii_capability"
    assert report["all_pass"] is True, report.get("gates")
    assert report["h0_plasticity"]["unprimed"] is True
    assert report["h0_plasticity"]["feature_axis"] == "scenario_id"
    assert report["h0_plasticity"]["split_n_min"] >= 24
    assert report["summary"]["hand_dev_edits"] >= 0
    assert (
        report["curves"]["man_full"][-1]["success_rate"]
        >= report["curves"]["static_aspect_graph"][-1]["success_rate"]
    )


def test_phase_ii_cli(tmp_path: Path) -> None:
    import subprocess

    out = tmp_path / "p2"
    env = {**os.environ, **_FORCE_STUB}
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "experiments/man_paper/phase_ii_run.py"),
            "--output",
            str(out),
            "--epochs",
            "10",
            "--provider",
            "stub",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads((out / "phase_ii_report.json").read_text(encoding="utf-8"))
    assert data["all_pass"] is True


def test_phase_ii_protocol_is_implemented_contract() -> None:
    from experiments.man_paper.phase_ii_protocol import (
        protocol_document,
        run_phase_ii_protocol,
    )

    protocol = run_phase_ii_protocol()
    assert protocol["status"] == "implemented_h0_harness"
    assert protocol["genesis"]["entrypoint"].endswith("seed_h0_graph")
    assert protocol["genesis"]["initial_edges"] == 0
    assert "skill_seed" not in protocol["implemented_harness"]["baselines"]
    doc = protocol_document()
    assert "Open \\todo" not in doc
    assert "deferred" not in doc.lower()
    assert "Implemented harness" in doc


def test_hand_iterated_patches_replace_seed_advice() -> None:
    from opencoat_runtime_protocol import Advice, AdviceType, Concern

    from experiments.man_paper.phase_ii_runner import _hand_patch_pool

    seed = Concern(
        id="seed",
        name="Seed",
        description="bootstrap",
        advice=Advice(type=AdviceType.RESPONSE_REQUIREMENT, content="generic bootstrap advice"),
    )
    cite, verify = _hand_patch_pool(seed)
    assert cite.advice is not None
    assert verify.advice is not None
    assert "documentation URL" in cite.advice.content
    assert "standard-library API" in verify.advice.content
    assert cite.advice.content != seed.advice.content
    assert verify.advice.content != seed.advice.content


def test_phase_ii_diagnostic_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCOAT_PHASE_II_FORCE_STUB", "1")
    from experiments.man_paper.phase_ii_runner import run_phase_ii_diagnostic

    report = run_phase_ii_diagnostic(provider="stub", limit=2)
    assert report["phase"] == "phase_ii_diagnostic"
    assert report["scenarios"] == 2
    assert report["traces"]
    first = report["traces"][0]
    assert "response" in first
    assert "injections" in first
    assert "active_concerns" in first


def test_phase_ii_training_variants_rotate_by_epoch() -> None:
    from experiments.man_paper.phase_ii_scenarios import (
        evaluate_phase_ii_reward,
        load_scenarios_for_epoch,
    )

    e0 = load_scenarios_for_epoch(family="coding_train", epoch=0)
    e1 = load_scenarios_for_epoch(family="coding_train", epoch=1)
    assert [s.id for s in e0] == [s.id for s in e1]
    assert any(a.user_text != b.user_text for a, b in zip(e0, e1, strict=True))
    assert all(s.variant_id.startswith("v") for s in e1)

    partial = evaluate_phase_ii_reward(
        scenario_id="ct-json",
        active_concern_ids=["c-01"],
        verifications=[],
        response="Use json.loads to parse the string.",
    )
    assert 0.0 < partial < 1.0
