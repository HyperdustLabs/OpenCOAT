# MAN paper — Phase II results (H0)

**Harness status:** implemented_h0_harness

Run: `bash scripts/run-man-paper-phase-ii.sh` → `PHASE_II_RESULTS.md`.

## H0 (primary)

Morphogenetic learning alone (zero code changes) raises competence on un-hand-built application scenarios; structure transfers to held-out and cross-domain settings.

*H1--H5 are mechanism ablations; Phase I pass is necessary but not sufficient for H0.*

## Signatures

- **Learning curve:** success/reward vs experience; no developer edits mid-run.
- **Transfer:** evolve on A; evaluate on held-out B and ≥1 cross-domain set;
  small A→B gap = testable surrogate for general competence.
- **Headline baseline:** developer-effort-matched hand-iterated agent;
  MAN should beat static and approach hand-iterated at ~zero dev effort.
- **Breadth & cost:** scenario-family coverage; cost-to-competence.

## Implemented harness

- **Genesis:** `experiments.man_paper.phase_ii_seed.seed_h0_graph`.
- **Cortex:** one intent_alignment concern from MAN_IDENTITY_PROMPT.
- **Conserved reflex:** `h0.conserved.fail-closed`.
- **Initial edges:** 0.
- **Scenario families:** coding_train, coding_heldout, openclaw_cross.
- **Baselines:** man_full, static_aspect_graph, hand_iterated.
- **Clean H0:** no plugin seeds, no SKILL.md concern upsert, no demo presets, no split-gate priming.

## Outputs

- `experiments/man_paper/results/PHASE_II_RESULTS.md`
- `experiments/man_paper/results/phase_ii_learning_curves.csv`
- `experiments/man_paper/results/phase_ii_report.json`

## Latest result

- **Report:** `experiments/man_paper/results/phase_ii_report.json`
- **All gates pass:** True
- **LLM:** `phase-ii-stub(forced)` (stub=True)
- **Epochs:** 10
- **MAN final success:** 0.8333333333333334
- **Static final success:** 0.0
- **Hand final success:** 0.8333333333333334
- **A→B gap:** 0.16666666666666663
- **H0 unprimed:** True
- **Feature axis:** `scenario_id`
- **Cumulative splits:** 2
- **Failed gates:** none

## Scope

Target: coding, openclaw.
“General” is operationalized (diverse held-out + cross-domain + breadth), not literal.

## Phase I prerequisite

Run first: `bash scripts/run-man-paper-experiments.sh` → `INTERNAL_VALIDITY.md`.