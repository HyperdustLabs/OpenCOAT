# MAN paper §8 experiments

Demo-backed harness aligned with `test_morphogenetic_paper_validation.py`.

```bash
# from repo root (daemon optional for live effector row)
bash scripts/run-man-paper-experiments.sh
```

| Output | Purpose |
| --- | --- |
| `results/report.json` | H1–H5 hypothesis payloads |
| `results/RESULTS.md` | Tables for LaTeX / review |

Suites: tool guard baselines (`suites.run_demo_tool_suite`), bimodal split (H2), tier-1 ρ ablation (H3), replay (conservation), soak stability (H5).
