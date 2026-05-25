# H0 genesis (合子) — single contract

Phase II / paper **H0** uses **one** genesis path. Product install and SkillLearnBench
have **different** seeds; do not mix them into H0 attribution.

## Three genesis paths in the repo

| Path | Where | What gets seeded | H0? |
| --- | --- | --- | --- |
| **H0 experimental** | `experiments/man_paper/phase_ii_seed.py` | Startup prompt → `extract_for_intent_alignment` (cortex) + optional **conserved reflex** (brainstem) | **Yes — canonical** |
| **Product / plugin** | `opencoat_runtime_cli/plugin_templates/*/bootstrap_opencoat.py` | `seed_concerns()` / `seed_stores()` — hand-authored plugin scaffold | **No** — install/dogfood only |
| **Skill file injection** | SkillLearnBench `SKILL.md` → solving agent (or mistaken “Concern init”) | Pre-written skill text | **No for `man_full`** — use as **`skill_seed` baseline** only |

## H0 graph at \(t=0\) (`seed_h0_graph`)

After `seed_h0_graph()`:

1. **Cortex (plastic)** — exactly **one** concern from:

   > Start up. You are a Self-Evolving Agent via Reward-Modulated Structural Plasticity over an Externally Reasoning LLM.

   - `source.origin = intent_alignment`
   - `reflex: false` — subject to warm plasticity / lifecycle
   - `pointcut`: `before_response`, `match: null` (joinpoint-only)

2. **Conserved core (non-plastic)** — `h0.conserved.fail-closed`

   - `reflex: true`, `neuron_type: inhibitory`
   - Deterministic TOOL_GUARD on destructive shell patterns (`before_tool_call`)
   - Excluded from `⇩_slow` structural rewrite (`PlasticityEngine` / connectome `is_conserved`)

3. **Edges** — **0** at genesis (`dcn.add_node` only; co-activation / cold wiring comes later).

This is **not** “pure single-cell with no brainstem”: it matches v0.3’s split between
**A_reflex** (fail-closed invariant) and **excitatory cortex** (morphogenetic target).

## What H0 explicitly does **not** use

- `02_coding_agent_demo` / `04_openclaw_with_runtime` `seed_concerns()`
- `demo-tool-block` or other Phase I fixtures
- Plugin `bootstrap_opencoat.seed_stores()` presets
- **SKILL.md → Concern upsert** as MAN’s initial graph (pollutes “what did morphogenesis grow?”)

## SkillLearnBench alignment

| Config | Genesis |
| --- | --- |
| **`man_full`** | H0 bare graph (`phase_ii_seed.seed_h0_graph`) inside runtime; skills are **exports** after learning (Mode A), not the seed |
| **`static_aspect_graph`** | Same H0 seed, plasticity off |
| **`hand_iterated`** | H0 seed + developer patches on failure (Phase II harness) |
| **`skill_seed` / b1-style** | Pre-authored `SKILL.md` only — **separate baseline**, compare against `man_full` to quantify **seed vs grow** |

See [`skilllearnbench-h0-integration-plan.md`](skilllearnbench-h0-integration-plan.md).

## Clean H0 plasticity (no priming)

Phase II **`man_full`** must **not** hand-prime split gates (contrast with Phase I H3 in
`ablations.py`, which uses `reinforce(δ=0)×5` + `reinforce(δ=0.15)` so cold split is eligible on
fixtures).

| Gate | Organic source in H0 |
| --- | --- |
| `buffer ≥ 8` | `CreditField.attribute_turn` per woven turn (cortex in `active`) |
| `state == reinforced` | First `lifecycle.reinforce` from warm `PlasticityEngine.reweight` on positive `r − b` |
| `activations ≥ 3` | Three reinforce events (weaken does not count) |
| `score ≥ 0.65` | Cumulative `min(|advantage|·step_delta, step_delta)` from successes — **bottleneck** |

Harness: `experiments/man_paper/phase_ii_runner.py` — no bootstrap `reinforce(δ=0)`, no fixed
`0.1/0.02` score bumps; `turn_complete` rows carry `active_aspects` + `reward` for cortex
attribution; EMA baseline (`baseline_ema_alpha≈0.22`); **stable split axis**
`payload["feature"] = scenario_id` (never LLM response text — see `credit_field._feature_from_record`);
`split_spec` uses **categorical equality** or token axes (not `feat in long_string`);
`split_n_min≥24`, **Welch** mean-gap test, **score EMA** for split eligibility;
optional `rollout_k>1` averages `r` per context (pass^k denoise).
Report **`first_split_epoch`**, **`last_split_guard_reason`**, and `h0_plasticity` in
`phase_ii_report.json` (measured, not preset). Do **not** lower θ_sep / δ_min or prime scores to force split.

**Lift vs split:** both use EMA score for gates; reflex lift runs only after `buffer ≥ n_min` and
split guards decline (no `lift_score=0.96` shortcut). **β≈0.01** scales ΔF complexity to binary
rewards (`G > 8β`); θ_sep and Welch carry the structural load.

**Ablation (contrast arm only):** `--feature-mode text` writes LLM output into buffer `feature`
(format-drift control). Default `scenario_id` for `man_full`; never mix into the primary H0 arm.

## Code entry

```python
from experiments.man_paper.phase_ii_seed import seed_h0_graph

cortex = seed_h0_graph(llm, store=store, dcn=dcn)
# cortex.id → bootstrap_id for MAN lifecycle / plasticity
```
