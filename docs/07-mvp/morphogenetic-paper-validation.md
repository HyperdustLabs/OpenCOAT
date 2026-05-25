# Morphogenetic paper validation (§7–§8)

Two layers (paper §8):

| Layer | Hypothesis | Status | Entry |
| --- | --- | --- | --- |
| **Phase I** | H1–H5 (+ F1–F3 foundations) | **Done** on fixtures | `bash scripts/run-man-paper-experiments.sh` |
| **Phase II** | **H0** self-evolution capability | **Runnable** (coding + OpenClaw stub) | `bash scripts/run-man-paper-phase-ii.sh` |

Phase I proves mechanisms per spec; passing Phase I is **necessary but not sufficient** for H0.
Phase II will show learning curves (no mid-run dev edits), A→B/cross-domain transfer, and
MAN vs static vs developer-effort-matched hand-iterated baselines on coding/OpenClaw scenarios.

---

## Phase I authenticity (what is “real” vs proxy)

| ID | Data source | Real runtime path? | Known proxy / caveat |
| --- | --- | --- | --- |
| **H1** | `h1_longitudinal.csv` | **Yes** — `EffectorKernel.run_turn`, `lifecycle.reinforce` on success, `guard_score` = `concern.score`; warm `step_delta≈0`, no cold in H1 epoch | CPS = planner + fractional verifier, **not** billed LLM tokens |
| **H2** | `r_t_bimodal` + `r_t_bandit` JSONL | **Yes** — `CreditField`, `evaluate_split_guards`, variance on buffer | No live agent loop; fixture replay only |
| **H3 ρ** | single activation vector | **Yes** — `tier1_responsibility` math | Not a multi-episode run |
| **H3 plasticity** | bandit JSONL | **Yes** — `split_with_spec_or_keywords` | Parent **primed** with `reinforce(δ=0.15)` so cold split is eligible (fixture scaffolding) |
| **H4 ρ** | synthetic hard/soft pair | **Yes** — tier-1 ρ | Not stochastic LLM |
| **H4 noise** | simulated Bernoulli outcomes | **No** — Monte Carlo outcome noise | ρ gap real; outcome variance **simulated** |
| **H5 soak** | `r_t_soak_long.jsonl` | **Yes** — append RT + `warm`/`cold` plasticity | Was wrongly on 32-row bimodal only — **fixed** to soak file |
| **F1–F3** | bimodal JSONL | **Yes** — replay / λ / β on buffer | — |
| **Main table** | demo-tool 40 turns | Partial | Illustrative baselines only |

**Not Phase I:** application Self-Evolving (H0), real token curves, hand-iterated baseline.

---

## Phase II (H0)

```bash
bash scripts/run-man-paper-phase-ii.sh
```

Runs Phase I first, then **H0 genesis** only (`experiments/man_paper/phase_ii_seed.py` —
see [`docs/design/h0-genesis.md`](../design/h0-genesis.md)): startup prompt → one
`intent_alignment` **cortex** concern + optional conserved reflex `h0.conserved.fail-closed`.
**No** plugin `seed_stores()`, **no** `SKILL.md` concern init, **no** demo coding/OpenClaw
presets. Cross-domain scenarios use the same H0 graph on `before_response` (tool-style cases
judged from LLM refusal text when effector path is not exercised).
**LLM:** auto-detect from env (**B.AI first**, same order as daemon `provider: auto`):

```bash
# B.AI (recommended on this machine)
export BAI_API_KEY='sk-...'
export BAI_MODEL='gpt-5.2'   # optional; default gpt-5.2
uv run python experiments/man_paper/phase_ii_run.py --epochs 20

# Or explicit
uv run python experiments/man_paper/phase_ii_run.py --provider bai --epochs 20

# Other providers
export OPENAI_API_KEY=...
uv run python experiments/man_paper/phase_ii_run.py --provider openai --epochs 20

# Load from ~/.opencoat/opencoat.env (if BAI_API_KEY is there)
set -a && source ~/.opencoat/opencoat.env && set +a
uv run python experiments/man_paper/phase_ii_run.py --epochs 20

# CI / offline: prompt-aware stub
OPENCOAT_PHASE_II_FORCE_STUB=1 uv run python experiments/man_paper/phase_ii_run.py --provider stub
```

See [`docs/config/bai-llm.md`](../config/bai-llm.md).

With a **real** LLM, gates use the `real_llm_advisory` profile (exit 0 unless `--strict-gates`).
Stub mode keeps strict gates for CI.

| Output | Content |
| --- | --- |
| `results/PHASE_II_RESULTS.md` | Learning curves + transfer + H0 gates |
| `results/phase_ii_learning_curves.csv` | `mode, epoch, success_rate, …` |
| `results/phase_ii_report.json` | Full report |

**Clean H0:** no split-gate priming — score/activations/reinforced state come only from
`r − baseline` via `turn_complete` warm reweight + credit buffer; cold split enabled; see
[`h0-genesis.md`](../design/h0-genesis.md). Phase I H3 still uses primed fixtures for
*mechanism* validity only.

**Before B.AI (budget):**

1. Stub precheck (free): `OPENCOAT_PHASE_II_FORCE_STUB=1 uv run python experiments/man_paper/phase_ii_run.py --epochs 8` — confirm `first_split_epoch` and `split_guard_reason` evolve (expect split by ~epoch 4 with `split_n_min=24`).
2. B.AI pilot: `--epochs 3` — watch `split_guard_reason` (plumbing vs signal vs denoise).
3. Full run: `--epochs 20`. Contrast arm only: `--feature-mode text` (format drift).

Baselines: **MAN** (single extracted concern + RT + lifecycle; structure grows via plasticity only),
**static** (same bootstrap concern, frozen score, no plasticity), **hand_iterated** (bootstrap +
hand patches on failure, dev budget 3). Transfer: `coding_heldout`, `openclaw_cross`.

Bootstrap: [`docs/design/h0-genesis.md`](../design/h0-genesis.md) — *Start up. You are a
Self-Evolving Agent…* → `extract_for_intent_alignment` (cortex) + `h0.conserved.fail-closed`
(reflex core, `reflex: true`).

Live OpenClaw gateway (product path, not H0 harness): daemon + bridge per
`integrations/openclaw-opencoat-bridge/README.md` uses **plugin** genesis, not `seed_h0_graph`.

---

## Phase I: how to read the data

Phase I is **not** a large benchmark. It is a **mechanism harness** with boolean gates on small,
deterministic fixtures. Start here:

| Read first | Why |
| --- | --- |
| `experiments/man_paper/results/INTERNAL_VALIDITY.md` | Scale table, pitfalls, gates, H1 summary, per-H metrics |
| `experiments/man_paper/results/h1_longitudinal.csv` | Epoch × mode CPS/success (plot-friendly) |
| `experiments/man_paper/results/internal_validity.json` | Machine-readable gates + `scale` block |
| `RESULTS.md` | **Auxiliary only** — tiny demo-tool loop, easy to misread |

### Fixture profiles (`fixtures/morphogenetic/scale.json`)

| Profile | Bandit rows | Soak rows | H1 default |
| --- | --- | --- | --- |
| `standard` | 96 | 256 (8×32) | 20 epochs × 60 trials |
| **`stress`** (default) | 384 | 1024 (32×32) | 20 epochs × 60 trials |

Regenerate stress fixtures:

```bash
uv run python scripts/generate_morphogenetic_validation_data.py --scale stress
```

Legacy smaller set: `--scale standard`.

### Four pitfalls (do not misread)

1. **H1 `llm_calls_per_success`** — counts symbolic planner/verifier steps, not OpenAI tokens.
2. **Main table in `RESULTS.md`** — ~40-turn demo; not the H1 learning curve.
3. **H3** — often `tier1_splits=1` vs `uniform_splits=0`; not a large spurious-split study.
4. **H5 soak** — bounded span on repeated bimodal replay; not Phase II competence growth.

---

## Generate fixtures

```bash
uv run python scripts/generate_morphogenetic_validation_data.py --scale stress
```

Writes JSONL under `packages/opencoat-runtime/tests/fixtures/morphogenetic/` plus `scale.json`.

## Run validation

```bash
uv run pytest packages/opencoat-runtime/tests/integration/test_morphogenetic_paper_validation.py -v
```

## Paper §8 Phase I harness

```bash
bash scripts/run-man-paper-experiments.sh
```

Fixtures (stress) + mechanism pytest + `experiments/man_paper/run.py`. **Exit 1** if any
Phase I gate (H1–H5, F1–F3) fails.

Outputs:

| Artifact | Content |
| --- | --- |
| `results/INTERNAL_VALIDITY.md` | **Primary** — scale, pitfalls, gates, metrics |
| `results/h1_longitudinal.csv` | H1 curve data |
| `results/internal_validity.json` | Gates + `scale` |
| `results/PHASE_II_PROTOCOL.md` | H0 preregistration |
| `results/report.json` | Full dump + auxiliary tables |
| `results/RESULTS.md` | Demo baselines, sweeps (secondary) |

Tests: `test_morphogenetic_internal_validity.py`, `test_man_paper_full_empirical.py`.

## What is verified (mechanism unit tests)

| Paper claim | Test |
| --- | --- |
| Credit conservation `Σκ_a ≈ r−b` | `test_credit_conservation_on_fixture` |
| JSONL replay deterministic | `test_replay_deterministic_scores_and_edges` |
| Split lowers child variance | `test_split_reduces_reward_variance` |
| Eligibility trace `e ← λe + α·part` | `test_eligibility_trace_accumulates_and_decays` |
| Tier-1 ρ weights hard > soft | `test_tier1_vs_uniform_responsibility_spread` |
| Graph evolution from session | `test_rt_service_session_grows_connectome` |

## Implementation map

- `credit/eligibility.py` — `e_a`, `e_s`
- `credit/baseline.py` — context bucket `b`
- `credit/attribution.py` — tier-1 `ρ`
- `credit/credit_field.py` — conserved κ + synapse ledger
- `credit/synapse_ledger.py` — κ_s → edge LTP
- `credit/tier2_calibration.py` — deterministic LOO on buffer
- `credit/rt_replay.py` — full replay harness
- `experiments/man_paper/` — Phase I harness (`internal_validity.py`, `phase_i_readme.py`)
