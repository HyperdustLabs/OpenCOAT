# Naming: `weave_id` vs `host_round_id` (v0.2 wire)

## Problem

**Turn** overloaded two concepts:

| Old name | Meaning |
| --- | --- |
| `turn_id` on `JoinpointEvent` | Host agent **dialog round** (e.g. OpenClaw `runId`) |
| `turn_id` on `ConcernInjection` / `ConcernVector` | OpenCOAT **one joinpoint weave run** |
| `TurnLoop` | Pipeline for **one joinpoint**, not one dialog turn |

## Resolution (0.2.0 wire)

| Field / type | Role |
| --- | --- |
| **`JoinpointPipeline`** | Renamed from `TurnLoop` (`TurnLoop` remains a deprecated alias). |
| **`weave_id`** | One joinpoint weave run, minted as `weave-{joinpoint.id}` by the runtime. |
| **`host_round_id`** | Optional host dialog round on `JoinpointEvent`, `ConcernVector`, `ConcernInjection`. |

## Backward compatibility

- JSON **`turn_id`** on ingest maps to `host_round_id` (joinpoints) or `weave_id` (injection/vector) via Pydantic validators.
- Class alias **`TurnLoop = JoinpointPipeline`** for one release.

## Host guidance

- Pass **`host_round_id`** (not `turn_id`) on joinpoints when correlating with your agent run / `runId`.
- Expect **`weave_id`** on injections; use it for debug/replay (`GET /v1/injection/{weave_id}`).
