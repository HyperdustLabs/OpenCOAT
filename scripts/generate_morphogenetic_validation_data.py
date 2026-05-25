#!/usr/bin/env python3
"""Generate deterministic fixtures for morphogenetic paper validation (§8)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "opencoat-runtime"))

from opencoat_runtime_core.credit.r_t_record import RtRecord, RtSignal  # noqa: E402
from opencoat_runtime_protocol import (  # noqa: E402
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    PointcutDef,
    PointcutMatch,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)

OUT = ROOT / "packages/opencoat-runtime/tests/fixtures/morphogenetic"


def _bimodal_concern() -> Concern:
    return Concern(
        id="paper.bimodal-guard",
        name="Paper bimodal tool guard",
        reflex=True,
        neuron_type="inhibitory",
        pointcuts=[
            PointcutDef(
                id="pc-paper",
                expression="before_tool_call()",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["destructive", "benign"]),
            )
        ],
        advices=[
            AopAdvice(
                id="adv-paper",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-paper",
                content="Paper validation guard",
                template=AdviceType.TOOL_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.TOOL_LEVEL,
                    target="tool_call.arguments",
                    priority=0.9,
                ),
            )
        ],
    )


def _bandit_parent() -> Concern:
    return Concern(
        id="paper.bandit-parent",
        name="Paper bandit parent (splittable)",
        reflex=False,
        neuron_type="excitatory",
        pointcuts=[
            PointcutDef(
                id="pc-bandit",
                expression="before_tool_call()",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["zone:alpha", "zone:beta"]),
            )
        ],
        advices=[
            AopAdvice(
                id="adv-bandit",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-bandit",
                content="context bandit",
                template=AdviceType.REASONING_GUIDANCE,
                effect=WeavingPolicy(
                    mode=WeavingOperation.INSERT,
                    level=WeavingLevel.PROMPT_LEVEL,
                    target="prompt.system",
                    priority=0.5,
                ),
            )
        ],
    )


def _bandit_records(*, rows: int = 96, noise: float = 0.0) -> list[RtRecord]:
    """Partitioned bandit: optimal r=1.0 when zone matches reward arm."""
    import random

    rng = random.Random(42)
    ts = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    out: list[RtRecord] = []
    for i in range(rows):
        zone = "zone:alpha" if i % 2 == 0 else "zone:beta"
        r = 1.0 if zone == "zone:alpha" else 0.0
        if noise > 0 and rng.random() < noise:
            r = 1.0 - r
        out.append(
            RtRecord(
                ts=ts,
                session_id="bandit-session",
                turn_id=f"bandit-{i}",
                joinpoint="before_tool_call",
                hook="before_tool_call",
                signal=RtSignal(
                    kind="tool_outcome",
                    tool_name="shell.exec",
                    payload={
                        "feature": zone,
                        "zone": zone,
                        "active_aspects": [
                            {
                                "concern_id": "paper.bandit-parent",
                                "activation_score": 0.9,
                                "hard": False,
                            }
                        ],
                    },
                    reflex={"policy_id": "paper.bandit-parent", "decision": "observe"},
                ),
                r=r,
            )
        )
    return out


def _soak_long_records(*, repeats: int = 8) -> list[RtRecord]:
    base = _records()
    out: list[RtRecord] = []
    for rep in range(repeats):
        for rec in base:
            out.append(
                rec.model_copy(
                    update={
                        "session_id": f"soak-{rep}",
                        "turn_id": f"{rec.turn_id}-r{rep}",
                    }
                )
            )
    return out


def _records() -> list[RtRecord]:
    ts = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    rows: list[RtRecord] = []
    for i in range(32):
        destructive = i % 2 == 0
        feature = "destructive" if destructive else "benign"
        r = 1.0 if destructive else 0.0
        rows.append(
            RtRecord(
                ts=ts,
                session_id="paper-session",
                turn_id=f"turn-{i}",
                joinpoint="before_tool_call",
                hook="before_tool_call",
                signal=RtSignal(
                    kind="tool_blocked" if destructive else "tool_outcome",
                    tool_name="shell.exec",
                    reflex={
                        "policy_id": "paper.bimodal-guard",
                        "decision": "deny" if destructive else "allow",
                    },
                    payload={
                        "command": f"rm -rf /tmp/{i}" if destructive else "ls -la",
                        "feature": feature,
                        "active_aspects": [
                            {
                                "concern_id": "paper.bimodal-guard",
                                "activation_score": 0.85,
                                "hard": True,
                            },
                            {
                                "concern_id": "paper.soft-hint",
                                "activation_score": 0.4,
                                "hard": False,
                            },
                        ],
                    },
                ),
                r=r,
            )
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Morphogenetic Phase I fixtures")
    parser.add_argument(
        "--scale",
        choices=("standard", "stress"),
        default="stress",
        help="standard: 96 bandit / 256 soak; stress: 384 bandit / 1024 soak (bimodal stays 32)",
    )
    args = parser.parse_args()
    bandit_rows = 96 if args.scale == "standard" else 384
    soak_repeats = 8 if args.scale == "standard" else 32
    soak_rows = 32 * soak_repeats

    OUT.mkdir(parents=True, exist_ok=True)
    concern_path = OUT / "bimodal_concern.json"
    concern_path.write_text(
        json.dumps(_bimodal_concern().model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    soft = _bimodal_concern().model_copy(
        update={
            "id": "paper.soft-hint",
            "name": "Paper soft hint",
            "reflex": False,
            "neuron_type": "excitatory",
        }
    )
    (OUT / "soft_hint_concern.json").write_text(
        json.dumps(soft.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    rt_path = OUT / "r_t_bimodal.jsonl"
    with rt_path.open("w", encoding="utf-8") as fh:
        for rec in _records():
            fh.write(json.dumps(rec.model_dump(mode="json")) + "\n")
    bandit_c = _bandit_parent()
    (OUT / "bandit_parent_concern.json").write_text(
        json.dumps(bandit_c.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    for noise, suffix in ((0.0, ""), (0.15, "_noisy")):
        bp = OUT / f"r_t_bandit{suffix}.jsonl"
        with bp.open("w", encoding="utf-8") as fh:
            for rec in _bandit_records(rows=bandit_rows, noise=noise):
                fh.write(json.dumps(rec.model_dump(mode="json")) + "\n")
        print(f"Wrote {bp} ({bandit_rows} rows)")

    soak_path = OUT / "r_t_soak_long.jsonl"
    soak_rows_list = _soak_long_records(repeats=soak_repeats)
    with soak_path.open("w", encoding="utf-8") as fh:
        for rec in soak_rows_list:
            fh.write(json.dumps(rec.model_dump(mode="json")) + "\n")
    print(f"Wrote {soak_path} ({len(soak_rows_list)} rows)")

    scale_manifest = {
        "profile": args.scale,
        "bimodal_rows": 32,
        "bandit_rows": bandit_rows,
        "bandit_noisy_rows": bandit_rows,
        "soak_rows": soak_rows,
        "soak_repeats": soak_repeats,
        "h1_epochs_default": 20,
        "h1_trials_per_epoch": 60,
    }
    (OUT / "scale.json").write_text(
        json.dumps(scale_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT / 'scale.json'} ({args.scale})")

    print(f"Wrote {concern_path}")
    print(f"Wrote {rt_path} ({len(list(_records()))} rows)")


if __name__ == "__main__":
    main()
