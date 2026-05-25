# Phase II results (H0 application)

**LLM:** `phase-ii-stub(forced)` (stub=True)
**Gates profile:** stub_strict
**All gates pass:** True
**Epochs:** 10 (no mid-run code edits on MAN/static)

## Learning curves (final epoch)

| Mode | Success | Dev edits | Aspects | Splits |
| --- | --- | --- | --- | --- |
| man_full | 0.83 | 0 | 4 | 2 |
| static_aspect_graph | 0.00 | 0 | 1 | 0 |
| hand_iterated | 0.83 | 3 | 11 | 4 |

## Transfer (MAN frozen after train)

| Split | Success | n |
| --- | --- | --- |
| coding_heldout | 1.00 | 4 |
| openclaw_cross | 1.00 | 4 |

**A→B gap (MAN train vs held-out):** 0.17
**Scenario families:** 3

## Gates

- **H0_man_beats_static_final**: PASS
- **H0_man_near_hand_low_dev**: PASS
- **H0_learning_curve_rises**: PASS
- **H0_transfer_heldout_ok**: PASS
- **H0_cross_domain_ok**: PASS
- **H0_transfer_gap_bounded**: PASS