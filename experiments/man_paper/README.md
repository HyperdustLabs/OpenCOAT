# MAN paper §8 experiments

Phase I is a mechanism harness aligned with
`test_morphogenetic_paper_validation.py`. Phase II is the H0 application harness:
a bare MAN genesis graph, stochastic graph-rewrite plasticity, and MAN/static/hand
baselines over adaptive coding/OpenClaw-style scenarios.

```bash
# from repo root (daemon optional for live effector row)
bash scripts/run-man-paper-experiments.sh

# H0 / Phase II
bash scripts/run-man-paper-phase-ii.sh
```

| Output | Purpose |
| --- | --- |
| `results/report.json` | Phase I H1–H5 hypothesis payloads |
| `results/RESULTS.md` | Phase I tables for LaTeX / review |
| `results/PHASE_II_RESULTS.md` | Phase II learning curves, transfer, and H0 gates |
| `results/phase_ii_report.json` | Machine-readable Phase II report |
| `results/diagnostics/*` | limit-N provider diagnostics, including B.AI runs |

Suites: tool guard baselines (`suites.run_demo_tool_suite`), bimodal split (H2), tier-1 ρ ablation (H3), replay (conservation), soak stability (H5).

Useful direct commands:

```bash
# Real LLM, auto provider order: B.AI → OpenAI → Anthropic → Azure → stub
uv run python experiments/man_paper/phase_ii_run.py --provider bai --epochs 20

# Budget diagnostic
uv run python experiments/man_paper/phase_ii_diagnose.py --provider bai --limit 2

# Hermetic CI / offline stub
OPENCOAT_PHASE_II_FORCE_STUB=1 uv run python experiments/man_paper/phase_ii_run.py --provider stub
```

Phase II tasks are not static prompt repeats. `fixtures/phase_ii/scenarios.json`
defines canonical task families; `phase_ii_scenarios.py` mutates variants across
epochs; `phase_ii_runner.py` records `r_t`, updates κ/baselines/eligibility, and
lets slow plasticity accept split/connect/prune/merge/lift rewrites only when the
reward evidence and guards justify them.
