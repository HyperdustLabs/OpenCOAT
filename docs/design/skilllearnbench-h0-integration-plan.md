# SkillLearnBench × OpenCOAT/MAN — H0 integration plan

**Status:** Plan only (no `phase_ii_skilllearnbench.py` in-tree yet). **H0 genesis is unified**
in [`h0-genesis.md`](h0-genesis.md) — **not** plugin `seed_stores()` and **not** SKILL.md → Concern
upsert for `man_full`. Full Docker eval deferred.
**Scope:** wire SkillLearnBench (`github.com/cxcscmu/SkillLearnBench`, CMU, arXiv 2604.20087)
into the existing `experiments/man_paper/` Phase II (H0) harness, mirroring the
`phase_ii_webarena.py` adapter pattern.
**Companion (deferred):** ELL-StuLife for the long-horizon facet H0 that SkillLearnBench
cannot test (see [§10](#10-risks--impedance-mismatches)).

This plan is grounded in a read of the actual repo at clone time (commit on `main`,
May 2026), not the paper abstract. Where the shipped code disagrees with the homepage,
the code wins and is flagged.

---

## 1. What H0 facets SkillLearnBench can and cannot test

H0 = *morphogenetic learning alone (zero code changes) raises competence on un-hand-built
scenarios; structure transfers to held-out and cross-domain settings.* That bundles four
facets. SkillLearnBench covers two cleanly, one weakly, one not at all:

| H0 facet | SkillLearnBench coverage |
| --- | --- |
| **Structure absorbs cognition** (same success at lower cost) | **Strong** — native pass rate + per-trial `steps_used` |
| **Transfer / generalize, not overfit** | **Strong (cross-category) / Weak (within-task)** — 6 categories vs 2–6 instances/task |
| **Non-drifting self-evolution** | **Strong foil** — the paper's own b2 result (self-feedback drifts) is the bar to beat |
| **Competence rises over *many* episodes (lifelong)** | **None** — learning horizon is K≤3 rounds from one instance → that is ELL-StuLife's job |

Conclusion: SkillLearnBench is the right **sample-efficient-induction + transfer** anchor.
It is **not** the long-horizon self-evolution anchor. Do not let it carry H0 alone; pair
with StuLife. Stating this boundary in §8 of the paper pre-empts the obvious reviewer
objection.

---

## 2. What SkillLearnBench actually is (grounded)

**Decoupled generate→evaluate contract.** A "continual-learning method" is a *skill
generator*: it consumes `instance-1` of a task **without its verifier** and emits 1–5
`SKILL.md` files (YAML frontmatter `name`/`description` + markdown body — Claude skill
format). A fixed *solving agent* then consumes those skills and is scored. The two halves
are separate entry points:

- `generate_skills.py --tasks T --methods M --models LLM` → writes `skills/<method>-<model>/<task>/<skill>/SKILL.md`.
- `evaluate_skills.py --skill-path DIR [DIR2 none]` → injects skills into the solving
  agent (Docker), runs the verifier + LLM-judge, writes `output/evaluation_reports/<config>/report.csv`.

**Task structure.** `tasks/<task>/<task>-<n>/` per instance: `instruction.md`,
`environment/Dockerfile` (+ data), `tests/` (deterministic verifier: `test.sh`,
`test_outputs.py`, `expected_output.json`), `solution/solve.sh`, `task.toml` (timeouts,
cpus/mem, `allow_internet`). 20 tasks · 6 categories · 100 instances. Tasks are real and
hard (e.g. patch an Apache Druid CVE).

**Solving agent / judge.** Solving agent = Claude Code CLI (default `claude-sonnet-4-6`),
run inside a per-trial Docker container with skills injected at `/root/.claude/skills`,
capped by `--max-steps` (default 100). LLM-judge = `gpt-5-mini`. Agents registry in
`agents/__init__.py` also supports `codex` and `gemini-code`.

**Two method execution modes (this is the key seam).**

| Mode | Mechanism | MAN fit |
| --- | --- | --- |
| **toml-only** | `method.toml` (`skills_only_mode="interrupt"`); runner does single-pass gen+inject. Used by b1, b4. | MAN-as-generator (Mode A) |
| **plugin** | `method.py` exposing `run(*, container_name, task_path, trial_path, agent, model_name, instruction, task_workdir, max_rounds, max_steps) -> (passed, steps_used, stdout, stderr, rounds_used)`. The plugin **owns agent execution + verification**; runner owns container setup + artifact copy. Used by b3. | MAN runtime in the loop (Mode B) |

**Metrics — with one correction.** Three levels: Task Success (binary verifier pass),
Skill Quality (coverage, executability, safety — LLM-judge), Trajectory Quality
(key-point recall, order, completeness — LLM-judge). The **efficiency** signal shipped in
code is `steps_used` (tool-use step count) and `rounds_used`, **not raw tokens** — the
homepage says "token consumption" but `core/skill_runner.py` counts `tool_use` events.
This matters: our "same accuracy at lower cost" signal is denominated in **steps/rounds**
natively; token logging would be an add-on (trivial in Mode B since the plugin owns
execution).

**Free anchors.** The repo commits pre-generated skills for **b1–b4 × {haiku-4-5,
sonnet-4-6, opus-4-6, gemini-3-flash, gemini-3.1-flash-lite, gemini-3.1-pro}** plus
`skills/human_authored/`. So every comparison baseline and the human ceiling are already
present — no regeneration needed to position MAN.

**Requirements.** Docker is a hard requirement (per-trial containers). Keys:
`ANTHROPIC_API_KEY` (solving agent), `OPENAI_API_KEY` (judge), `GH_TOKEN` (one task only),
`GEMINI_API_KEY` (optional). `evaluate_skills.py --dry-run` previews without execution →
usable for pipeline validation with no keys and no Docker.

---

## 3. Genesis: H0 zygote vs skill injection (do not conflate)

| Genesis | Used by | Role |
| --- | --- | --- |
| **`seed_h0_graph`** (`phase_ii_seed.py`) | `man_full`, `static_aspect_graph`, Phase II | Bare startup prompt + conserved reflex + one cortex. **Morphogenesis grows from here.** |
| **Plugin `seed_stores()`** | `opencoat plugin install`, daemon dogfood | Product scaffold — **out of H0 attribution.** |
| **`SKILL.md` pre-seed** | Baseline **`skill_seed`** (≈ b1/b4) | Fast competence; **not** `man_full` init |

**Rule:** `man_full` must start from **`seed_h0_graph`** only. SKILL files are **exports**
(Mode A) or solving-agent injections (`skill_seed`), never Concern upserts at round 0.

## 4. Core design decision: Mode A vs Mode B

**Mode A — export after H0 learning.** Morphogenesis from `seed_h0_graph`, then serialize
to `SKILL.md` for the stock solving agent. Leaderboard-comparable; serializable slice only.

**Mode B — `method.py` plugin.** Runtime with `seed_h0_graph` + plasticity conditions solving
in-container. Faithful H0; not directly comparable to b1–b4.

Do **both**; report **A→B gap** (serializable vs live conditioning).

---

## 5. MAN baselines → SkillLearnBench configs

Reuse the Phase II harness modes plus benchmark foils. Genesis column is the critical
distinction:

| Harness mode | H0 genesis | SkillLearnBench role |
| --- | --- | --- |
| `man_full` | **`seed_h0_graph`** | System under test; plasticity ON; skills = **export** (A) or inline runtime (B) |
| `static_aspect_graph` | **`seed_h0_graph`** (frozen) | Morphogenesis off — same zygote, no slow dynamics |
| `hand_iterated` | **`seed_h0_graph`** + dev patches | Human-effort ceiling inside OpenCOAT harness |
| **`skill_seed`** *(new)* | **Pre-authored `SKILL.md` only** | One-shot injection baseline (≈ b1/b4); **not** MAN morphogenesis |
| *(null)* | none | `no_skill` floor |
| *(foil)* | n/a (benchmark b2) | self-feedback drift bar |
| *(reference)* | n/a | `b3`, `b1`, `b4`, `human_authored` committed skills |

**The sharp claim, in the benchmark's own terms:** MAN uses an *internal grounded* signal
(credit/responsibility), not pure self-critique. So the predicted, mechanistically-motivated
result is:

> `man_full` (no teacher) **beats** `b2-self-feedback` (no teacher, drifts) and
> **approaches** `b3-teacher-feedback` / `human_authored` — i.e. MAN gets teacher-quality
> improvement without a teacher.

If `man_full` merely ties `b2`, that is honest evidence MAN is "fancy self-feedback that
also drifts" — exactly the falsification a [[user-opencoat-evaluation]]-style audit should
want available.

---

## 6. H0 signatures → SkillLearnBench metrics

| H0 signature | Concrete measurement here | Gate (mirrors webarena gate vocabulary) |
| --- | --- | --- |
| Learning curve rises | pass rate across rounds (b2/b3-style K rounds; or MAN's internal epochs in Mode B) | `H0_slb_curve_rises` (monotone + Δ≥0.12) |
| Structure absorbs cognition | pass rate held while `steps_used`/`rounds_used` ↓ | `H0_slb_equal_pass_lower_steps` |
| Beats hand-designed-frozen | `man_full` > `static_aspect_graph` on held-out | `H0_slb_man_beats_static_heldout` (+0.05) |
| Non-drift self-evolution | `man_full` > `b2-self-feedback` | `H0_slb_man_beats_self_feedback` |
| Approaches human ceiling | `man_full` heldout ≥ `human_authored` − 0.12 | `H0_slb_man_near_human` |
| Transfer, not overfit | held-out (cross-category) pass; bounded train→heldout gap | `H0_slb_A_to_B_gap` (≤0.35) |

`steps_used`/`rounds_used` are the attribution-clean currency: "same pass at fewer steps"
cannot be the base LLM trying harder.

---

## 7. Splits & seeds

Two split axes; the second is the one that matters for "general, not overfit":

- **Within-task instance split** — generate from `instance-1`, eval on `2..n`. This is the
  benchmark's native protocol but N is tiny (2–6/task), so held-out within a task is weak.
- **Cross-category split (primary)** — the 6 categories (Software Eng, Information
  Retrieval, Productivity, Data & Analytics, Content & Creative, Utilities). Evolve MAN on
  a *train* set of categories, hold out the rest. Proposed: **4 train / 2 held-out**
  categories. This is the real test that the learned structure is not category-overfit.
- **Seeds** — the solving agent is stochastic; run **≥3 trials/instance** and report CIs.
  Without seed variance a single rising curve is not evidence (stochastic-effector point).

Encode as `fixtures/skilllearnbench/splits.json`, mirroring the webarena fixture
(deterministic sha256 bucketing + a small pilot subset for CI). Add a `tasks_manifest.json`
listing the 20 tasks × category × instance counts.

---

## 8. How it slots into the existing harness (future glue)

**Not wired into `phase_ii_runner` today.** Phase II H0 = `phase_ii_seed.seed_h0_graph` only
([`h0-genesis.md`](h0-genesis.md)). SkillLearnBench is a **separate** adapter (planned):

```
experiments/man_paper/
  fixtures/skilllearnbench/
    README.md              # no SKILL.md concern seeds for man_full
    splits.json            # (planned) train/heldout categories
    tasks_manifest.json    # (planned)
  phase_ii_skilllearnbench.py   # (planned) scores exported skills only
```

Planned adapter responsibilities:

1. `load_splits()` / `load_tasks()` from fixtures.
2. Score **exported** skill trees per baseline —
   `{skills_root}/{man_full|static|skill_seed|…}/{train|heldout}/<task>/SKILL.md` via
   `evaluate_skills.py` / `report.csv` — **never** parse SKILL.md into `ConcernStore` for
   `man_full` initialization.
3. `man_full` skill **generation** (Mode A) or **plugin** (Mode B) runs **out-of-band** with
   **`seed_h0_graph`** as the only graph seed; adapter only scores artifacts.
4. Env: `OPENCOAT_SLB_SKILLS_ROOT`; skip when missing (like webarena log root).

Do **not** add `skilllearnbench = run_slb_h0(...)` to `run_phase_ii` until genesis wiring
is reviewed — keep SLB off the default `run-man-paper-phase-ii.sh` path until then.

---

## 9. Design guards for a valid H0 run

These are the difference between "a rising curve" and "a defensible H0 claim":

- **Frozen-code guard.** Pin MAN's git SHA for the whole run; assert `dev_edits == 0` in
  the curve rows (the field already exists); emit a diff guard so "no code changes" is
  *proven*, not asserted. Only MAN's learned structure/skills may change across rounds.
- **Learning on/off ablation.** `man_full` (plasticity ON) vs `static_aspect_graph`
  (structure frozen at round 0). If the curve rises only with plasticity on, the rise is
  attributable to morphogenesis — not to the solving agent or round ordering.
- **Stub caveat.** `PhaseIIStubLLM` (and any scripted solver) **cannot** support an H0
  conclusion here — it assumes away the stochastic effector that is OpenCOAT's whole point.
  Stub/`--dry-run` are for **pipeline validation only**. The H0 numbers need a real LLM.
- **Unit of analysis, stated honestly.** Mode A measures *MAN-authored skills + frozen
  Claude Sonnet 4.6 solving agent*; Mode B measures *MAN-conditioned solving*. Neither is
  "MAN alone." Report the composite and attribute only the **deltas** (static→man_full,
  man_full−b2) to MAN — consistent with the attribution ladder used for webarena.

---

## 10. Risks / impedance mismatches

1. **SKILL.md as genesis confounds H0.** If concerns are upserted from skills at round 0,
   gains may be **injection**, not morphogenesis. → `man_full` uses `seed_h0_graph` only;
   `skill_seed` is the explicit foil.
2. **Decoupling flattens MAN (Mode A).** Export to `SKILL.md` after learning does not
   exercise live credit at solve time. → Mode B + A→B gap.
3. **Tiny within-task N.** 2–6 instances/task → within-task transfer is statistically
   thin. → lean on the cross-category split as the primary transfer evidence.
4. **Short horizon ≠ lifelong.** K≤3 rounds is sample-efficient induction, not the
   many-episode self-evolution H0 ultimately claims. → that facet goes to ELL-StuLife.
5. **Cost & infra.** Docker + 2 paid APIs (Anthropic solver + OpenAI judge) per trial ×
   instances × seeds × baselines. Budget before any full run; start with the pilot subset.
6. **Effector/judge confound.** Solving agent is `claude-sonnet-4-6`; if MAN's effector is
   also a frontier Claude, "who is competent" blurs and contamination is possible. → keep
   the solving agent fixed across all baselines so it cancels in deltas; consider a
   different/cheaper solving model to widen headroom.
7. **steps ≠ tokens.** The free efficiency signal is steps/rounds. If the paper wants a
   token-cost claim, add token accounting in the Mode B plugin (it owns execution).
8. **Leaderboard non-comparability in Mode B.** Mode B leaves the stock solving path, so
   its numbers are not apples-to-apples with the public b1–b4 board. State this; keep Mode
   A numbers for the comparable column.

---

## 11. Phased execution (when you green-light leaving "plan only")

| Phase | Needs | Deliverable |
| --- | --- | --- |
| **0 — pipeline dry-run** | no keys, no Docker | clone pinned; `evaluate_skills.py --dry-run`; parse a committed b1/human `report.csv` through the new adapter; build `splits.json` + manifest. Proves the glue end-to-end on artifacts that already exist. |
| **1 — Mode A pilot** | Anthropic+OpenAI keys, Docker, small budget | MAN-as-generator on 1–2 categories; score vs `none`, `b2`, `human_authored`; first real `slb_*` gates. |
| **2 — Mode A full + cross-domain** | budget for 100 instances × seeds | full cross-category split; CIs; the leaderboard-comparable MAN column. |
| **3 — Mode B plugin** | MAN runtime + effector wired in-container | `method.py` plugin; faithful H0 number; A→B gap. |

Rough effort (excluding compute/$): Phase 0 ≈ 0.5–1 day (adapter + fixtures, all glue).
Phase 1 ≈ 1–2 days (H0 runtime learn → SKILL.md **export** serializer + run). Phase 3 ≈
several days (in-container MAN + `seed_h0_graph` plugin).

---

## 12. Open decisions for you

- **MAN effector model** for generation (and, in Mode B, for solving)?
- **Cross-category split**: confirm 4 train / 2 held-out, and which 2 are held out.
- **Mode A only, or A then B?** (recommendation: A then B, report the gap.)
- **Add token logging** on top of native `steps_used`?

Once these are set, Phase 0 is pure glue and needs neither keys nor Docker.
