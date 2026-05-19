# 07 — Meta governance heartbeat soak

Short stand-in for the M6 24h soak: exercises decay, merge/archive, and conflict
scan workers via repeated `OpenCOATRuntime.tick()` calls.

## Run (hermetic)

From repo root:

```bash
uv run python -m pytest packages/opencoat-runtime/tests/soak/test_heartbeat_maintenance_soak.py -q
```

## Run against a live daemon

1. `uv run opencoat runtime up` (confirm log: `heartbeat scheduler started`).
2. Leave running; watch concern count / DCN edges stabilize over hours.
3. Re-run `./scripts/verify-m6-prerequisites.sh` after long runs.

Full 24h soak harness and convergence metrics are tracked in
[`docs/07-mvp/post-m5-roadmap.md`](../../docs/07-mvp/post-m5-roadmap.md) (M6 PR4).
