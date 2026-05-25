# MAN paper — auxiliary metrics & tables

H1 epochs: 4 (profile `stress`). See `INTERNAL_VALIDITY.md` + `h1_longitudinal.csv`.

## Phase I gates

- **H1**: PASS
- **H2**: PASS
- **H3**: PASS
- **H4**: PASS
- **H5**: PASS
- **F1_replay**: PASS
- **F2_lambda**: PASS
- **F3_beta**: PASS

## Main table

| method | success_rate | llm_calls_per_success | reliability_gap | struct_stability |
| --- | --- | --- | --- | --- |
| llm_only | 0.500 | 2.000 | — | 0.000 |
| fixed_hand_prompt | 1.000 | 1.000 | 0.000 | 0.000 |
| static_aspect_graph | 1.000 | 1.000 | 0.000 | 0.000 |
| weight_only_plasticity | 1.000 | 1.000 | 0.000 | 0.000 |
| man_full | 1.000 | 1.000 | 0.000 | 0.000 |

## H1 longitudinal (last epoch CPS)

- llm_only: 2.33 (epoch0=2.33)
- static_aspect_graph: 1.00 (epoch0=1.00)
- man_full: 1.77 (epoch0=1.97)

## λ / β sweeps

### lambda
- 0.0: metric=1.2500 (max_resid=1.11e-16)
- 0.25: metric=1.6667 (max_resid=1.11e-16)
- 0.5: metric=2.5000 (max_resid=1.11e-16)
- 0.75: metric=4.9995 (max_resid=1.11e-16)
- 0.9: metric=12.0708 (max_resid=1.11e-16)
- 1.0: metric=40.0000 (max_resid=1.11e-16)
### beta
- 0.01: metric=1.0000 (accepted (categorical axis=benign))
- 0.02: metric=1.0000 (accepted (categorical axis=benign))
- 0.05: metric=0.0000 (ΔF ≥ 0)
- 0.1: metric=0.0000 (ΔF ≥ 0)
- 0.5: metric=0.0000 (ΔF ≥ 0)
- 1.0: metric=0.0000 (ΔF ≥ 0)

## Ablations

| method | success_rate | spurious_split_rate | notes |
| --- | --- | --- | --- |
| -- responsibility ρ (H3) | 1.000 | 0.717 | hard_minus_soft_rho=0.7172 uniform_spread=0.0000 |
| -- responsibility plasticity (H3) | 1.000 | 0.000 | tier1 spurious=0 splits=1; uniform spurious=0 splits=0 h3_ok=True |
| tier1_replay | 1.000 | — | deterministic=True max_residual=1.11e-16 |
| H4_hard_vs_soft | 1.000 | — | rho_hard=0.7407 rho_soft=0.2593 |
| tier2_ablation | 1.000 | 0.000 | splits_off=0 splits_on=0 |
| -- conserved reflex (H5) | 0.000 | 0.000 | on edge_span=0 stable=True; off edge_span=0 stable=True |
| h2_bandit_lift | 1.000 | — | lift=0.500 eligible=True |

## Live daemon
```json
{
  "ping": {
    "ok": true
  },
  "concern_upsert": {
    "id": "demo-tool-block",
    "kind": "concern",
    "neuron_type": "excitatory",
    "reflex": false,
    "generated_type": null,
    "generated_tags": [],
    "name": "Demo tool block",
    "description": "",
    "source": null,
    "chain_ref": null,
    "joinpoint_selectors": [],
    "pointcut": {
      "joinpoints": [
        "before_tool_call"
      ],
      "match": {
        "any_keywords": [
          "rm -rf",
          "rm  -rf"
        ],
        "all_keywords": null,
        "regex": null,
        "semantic_intent": null,
        "structure": null,
        "confidence": null,
        "risk": null,
        "history": null,
        "claim": null
      },
      "context_predicates": []
    },
    "advice": {
      "type": "tool_guard",
      "content": "Refusing destructive shell command.",
      "rationale": null,
      "max_tokens": null,
      "params": null
    },
    "weaving_policy": {
      "mode": "block",
      "level": "tool_level",
      "target": "tool_call.arguments",
      "max_tokens": 200,
      "priority": 0.9
    },
    "pointcuts": [
      {
        "id": "pc-tool",
        "expression": "before_tool_call()",
        "joinpoints": [
          "before_tool_call"
        ],
        "match": {
          "any_keywords": [
            "rm -rf",
            "rm  -rf"
          ],
          "all_keywords": null,
          "regex": null,
          "semantic_intent": null,
          "structure": null,
          "confidence": null,
          "risk": null,
          "history": null,
          "claim": null
        },
        "context_predicates": []
      }
    ],
    "advices": [
      {
        "id": "adv-block",
        "kind": "before",
        "pointcut_ref": "pc-tool",
        "content": "Refusing destructive shell command.",
        "template": "tool_guard",
        "rationale": null,
        "max_tokens": null,
        "params": null,
        "effect": {
          "mode": "block",
          "level": "tool_level",
          "target": "tool_call.arguments",
          "max_tokens": 200,
          "priority": 0.9
        }
      }
    ],
    "declarations": [],
    "graph_edges": [],
    "scope": null,
    "relations": [],
    "activation_state": null,
    "lifecycle_state": "created",
    "metrics": {
      "activations": 0,
      "satisfied": 0,
      "violated": 0,
      "tokens_used": 0
    },
    "created_at": null,
    "updated_at": null,
    "schema_version": "0.1.0"
  },
  "rm -rf /tmp/paper": {
    "allowed": false,
    "expect_allow": false,
    "ok": true
  },
  "ls -la": {
    "allowed": true,
    "expect_allow": true,
    "ok": true
  },
  "demo_ok": true
}
```