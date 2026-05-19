# opencoat-runtime

The OpenCOAT Runtime — Concern-Oriented Agent Thinking for LLM agents.

This package ships the entire runtime stack:

| Module                       | Layer | Role                                                |
| ---------------------------- | ----- | --------------------------------------------------- |
| `opencoat_runtime_core`      | L2    | pure logic: concern, joinpoint, pointcut, advice, weaving, COPR, coordinator, resolver, DCN, meta, loops, ports |
| `opencoat_runtime_storage`   | L3    | ConcernStore / DCNStore backends (memory, sqlite, postgres, jsonl, vector) |
| `opencoat_runtime_llm`       | L3    | LLM and embedder clients (openai, anthropic, azure, ollama, stub) |
| `opencoat_runtime_daemon`    | L4    | long-running daemon: scheduler, workers, IPC, HTTP/JSON-RPC API |
| `opencoat_runtime_cli`       | L4    | `opencoat` command-line interface                   |

Schemas and data envelopes live in the sibling [`opencoat-runtime-protocol`](https://pypi.org/project/opencoat-runtime-protocol/) package.
Host-side integration (joinpoint emitter + first-party framework adapters) lives in [`opencoat-runtime-host`](https://pypi.org/project/opencoat-runtime-host/).

## Install

```bash
pipx install opencoat-runtime          # core stack, no heavy deps
pipx install "opencoat-runtime[all]"   # + every optional backend SDK
```

Pick-your-own:

```bash
pip install "opencoat-runtime[postgres]"        # psycopg
pip install "opencoat-runtime[vector]"          # faiss-cpu
pip install "opencoat-runtime[openai]"          # openai SDK
pip install "opencoat-runtime[anthropic]"       # anthropic SDK
pip install "opencoat-runtime[http]"            # daemon HTTP transport (fastapi + uvicorn)
pip install "opencoat-runtime[grpc]"            # daemon gRPC transport
```

## Quick start

```bash
opencoat --version
opencoat concern import --demo
opencoat runtime up          # sqlite + HTTP JSON-RPC + heartbeat scheduler (M6)
opencoat-daemon --help
```

See <https://github.com/HyperdustLabs/OpenCOAT> for the full runtime guide.

## Heartbeat maintenance (M6)

When the daemon runs with `runtime.loops.heartbeat_enabled: true`, a background
thread invokes `OpenCOATRuntime.tick()` every `heartbeat_interval_seconds`
(default 30). Each tick:

1. **DecayWorker** — increases per-concern `activation_state.decay`, then weakens or archives.
2. **MergeArchiverWorker** — runs `DCNEvolver` to merge duplicates and archive cold weakened concerns.
3. **ConflictScannerWorker** — syncs `conflicts_with` edges into the DCN (background only; hot-path weave still uses `ConflictResolver`).
4. **MetaReviewWorker** — counts active `meta_concern` rows for governance review ticks.

Configure thresholds under `runtime.loops.maintenance` in your daemon YAML
(see [`docs/config/daemon.yaml.example`](https://github.com/HyperdustLabs/OpenCOAT/blob/main/docs/config/daemon.yaml.example)).

**JSON-RPC:** `joinpoint.submit` accepts optional `extract_from_chat: true` to run
`concern.extract` on user `messages[]` before weaving (needs a real LLM).

**Tests / soak:**

```bash
uv run python -m pytest packages/opencoat-runtime/tests/daemon/test_m6_workers.py -q
uv run python -m pytest packages/opencoat-runtime/tests/soak/test_heartbeat_maintenance_soak.py -q
```

**Prerequisites gate:** from repo root, `./scripts/verify-m6-prerequisites.sh` (daemon on `:7878`).

## License

Apache-2.0.
