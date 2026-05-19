# 07 — Meta governance heartbeat soak (M6)

Stand-in for the M6 **24h soak** exit criterion: the daemon's background
scheduler calls `OpenCOATRuntime.tick()`, which runs decay, merge/archive,
conflict scan, and (optionally) meta-review workers.

## Layout

```text
examples/07_meta_governance_soak/
└── README.md    ← you are here (no main.py — use daemon + pytest soak)
```

## Hermetic (CI)

From repo root — ten maintenance ticks in-process:

```bash
uv run python -m pytest packages/opencoat-runtime/tests/soak/test_heartbeat_maintenance_soak.py -q
```

## Live daemon

1. `opencoat runtime up` — log should include `heartbeat scheduler started`.
2. Optional: tune `runtime.loops.maintenance` in `~/.opencoat/daemon.yaml`
   (see [`docs/config/daemon.yaml.example`](../../docs/config/daemon.yaml.example)).
3. Leave running; periodically check `opencoat runtime snapshot` and
   `opencoat dcn activation-log`.
4. Re-run [`scripts/verify-m6-prerequisites.sh`](../../scripts/verify-m6-prerequisites.sh)
   after long runs.

## Related docs

- [`docs/07-mvp/m6-conflict-paths.md`](../../docs/07-mvp/m6-conflict-paths.md) — activation-time vs background conflict paths
- [`docs/07-mvp/post-m5-roadmap.md`](../../docs/07-mvp/post-m5-roadmap.md) — M6 PR split
- Root [`README.md`](../../README.md) — heartbeat overview
