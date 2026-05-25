# MAN paper — Phase I internal validity (§8 H1–H5)

Validates **components per spec** on preregistered fixtures. Regenerate: `bash scripts/run-man-paper-experiments.sh`.

**All pass:** True

## Data scale (current profile)

Profile: **`stress`** (see `fixtures/morphogenetic/scale.json`).

| Artifact | Rows / scale | Role |
| --- | --- | --- |
| `r_t_bimodal.jsonl` | 32 | H2 variance, F1 replay, F3 β |
| `r_t_bandit.jsonl` | 384 | H2 lift, H3 tier-1 plasticity |
| `r_t_bandit_noisy.jsonl` | 384 | H3 uniform-ρ stress |
| `r_t_soak_long.jsonl` | 1024 (32× bimodal) | H5 bounded soak |
| H1 longitudinal | 20 epochs × 60 trials | CPS proxy (not Phase II) |

Phase I = mechanism smoke at this scale. **Not sufficient for H0** (see `PHASE_II_PROTOCOL.md`).

## How to read these numbers (common pitfalls)

1. **`llm_calls_per_success` (H1) is not API token usage.** The harness counts
   planner + fractional verifier weight from **real** `concern.score`
   (`lifecycle.reinforce` per successful trial; warm step_delta≈0).

2. **The auxiliary main table (`RESULTS.md`) is a tiny demo loop (~40 turns).**
   Do not use it for effect sizes; use `h1_longitudinal.csv` and hypothesis metrics in
   `internal_validity.json`.

3. **H3 reports split counts (often 1 vs 0), not a large spurious-split rate study.**
   It checks that tier-1 ρ enables a valid cold split on the noisy bandit while uniform ρ does not.

4. **H5 soak measures bounded span on repeated bimodal replay, not growing competence.**
   Small aspect/edge counts are expected; Phase II (H0) owns learning curves on real scenarios.

## Gates

| ID | Pass | Claim (abbrev.) |
| --- | --- | --- |
| H1 | yes | LLM calls/success decreases as structure matures; success not degraded |
| H2 | yes | Split reduces within-child reward variance; partition improves sub-conte |
| H3 | yes | Responsibility-weighted ρ enables credit cleaning; uniform ρ blocks vali |
| H4 | yes | ρ_hard > ρ_soft; outcome variance gap favors hard under added noise |
| H5 | yes | r_t_soak_long.jsonl (1024 rows): edge span bounded; reflex-on retains re |

## Foundations

- **F1_replay**: PASS — Tier-1 replay is deterministic with conserved κ
- **F2_lambda**: PASS — Eligibility λ accumulates trace mass without breaking conservation
- **F3_beta**: PASS — ΔF split gate accepts low β, rejects high β on bimodal buffer

## H1 learning curve (symbolic CPS proxy)

| mode | epoch0 CPS | final CPS | final guard_score | mature |
| --- | --- | --- | --- | --- |
| `llm_only` | 2.33 | 2.33 | 0.000 | 0 |
| `man_full` | 1.97 | 1.77 | 0.174 | 0 |
| `static_aspect_graph` | 1.00 | 1.00 | 0.000 | 0 |

Full series: `h1_longitudinal.csv` (plot epoch vs `llm_calls_per_success`).

## Hypothesis metrics (from last run)

### H1 — PASS

- **Suite:** demo-tool-block, 20 epochs × 60 trials (kernel+lifecycle score)
- **Note:** CPS from planner + verifier weight 1−score/0.65; guard_score is lifecycle.reinforce per success (warm step_delta≈0, no synthetic ramp)
- **Metrics:**
  - `man_cps_epoch0`: 1.9672222222222224
  - `man_cps_final`: 1.7669637606837598
  - `man_success_final`: 1.0
  - `static_cps`: 1.0
  - `delta_cps_man`: 0.2002584615384626

### H2 — PASS

- **Suite:** r_t_bimodal.jsonl (32) + r_t_bandit.jsonl (384), ΔF guards
- **Note:** H2_pass=True parent_var=0.2500 child_vars=[0.0, 0.0]; lift=0.500 eligible=True
- **Metrics:**
  - `bimodal_notes`: H2_pass=True parent_var=0.2500 child_vars=[0.0, 0.0]
  - `bandit_lift_notes`: lift=0.500 eligible=True
  - `bimodal_parent_var`: 0.25

### H3 — PASS

- **Suite:** ρ pair + bandit (384) vs bandit_noisy (384)
- **Note:** spurious=0 splits=1; spurious=0 splits=0 h3_ok=True
- **Metrics:**
  - `rho_hard_minus_soft`: 0.7171717171717171
  - `tier1_splits`: 1
  - `uniform_splits`: 0
  - `tier1_mean_reward`: 0.5
  - `uniform_mean_reward`: 0.49609375

### H4 — PASS

- **Suite:** synthetic tied activation + simulated outcome noise sweep
- **Note:** rho_hard=0.7407 rho_soft=0.2593
- **Metrics:**
  - `reliability_gap_rho`: 0.48148148148148145
  - `noise_sweep_pass_count`: 3

### H5 — PASS

- **Suite:** r_t_soak_long.jsonl (1024 rows) + disable_reflex_core ablation
- **Note:** man H5_stable=True edge_span=0 reward_span=1.0 rows=1024 fixture=r_t_soak_long.jsonl; reflex edge_span=0 stable=True / edge_span=0 stable=True
- **Metrics:**
  - `soak_edge_span_man`: 0.0
  - `soak_edge_span_static`: 0.0
  - `soak_edges_man`: 2
  - `reflex_on_aspects`: 2
  - `reflex_off_aspects`: 1
