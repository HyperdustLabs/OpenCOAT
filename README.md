<p align="center">
  <img src="docs/opencoat-logo.png" alt="OpenCOAT Runtime logo" width="300" />
</p>

<h1 align="center">OpenCOAT</h1>

<p align="center">
  <strong>Open Concern-Oriented Agent Thinking Runtime</strong><br />
  a general-purpose, Concern-first cognitive runtime for LLM agents.
</p>

---

> OpenCOAT Runtime applies *Separation of Concerns* to **agent thinking** instead of program code,
> using `joinpoint / pointcut / advice / weaving` to organize, modulate, verify and evolve
> the way Host Agents reason, plan, call tools, write memory, and respond.

```text
OpenCOAT Runtime
= Concern-first Runtime
+ AOP-style Thinking Mechanism
+ Deep Concern Network
```

This repository is the reference implementation. It is `host-agnostic` — the runtime core does not
depend on any specific agent framework. Hosts (OpenClaw, Hermes, LangGraph, AutoGen, CrewAI, custom)
plug in via adapters.

---

## Status

Pre-alpha. We are working through the milestones defined in
[`docs/design/v0.2-system-design.md`](docs/design/v0.2-system-design.md) §12.

| Milestone | Scope | Status |
| --- | --- | --- |
| **M0** | Monorepo skeleton, JSON schemas, empty core skeleton, CI | ✅ complete |
| **M1** | In-proc happy path (memory + stub-llm + `01_simple_chat_agent`) | ✅ complete |
| **M2** | Real LLM (OpenAI / Anthropic / Azure) + extractor + lifecycle | ✅ complete — `OpenAILLMClient` ([PR-7 / #7](https://github.com/HyperdustLabs/OpenCOAT/pull/7)), `AnthropicLLMClient` ([PR-8 / #9](https://github.com/HyperdustLabs/OpenCOAT/pull/9)), `AzureOpenAILLMClient` ([PR-9 / #11](https://github.com/HyperdustLabs/OpenCOAT/pull/11)), `ConcernExtractor` ([PR-10 / #12](https://github.com/HyperdustLabs/OpenCOAT/pull/12)), `ConcernLifecycleManager` ([PR-11 / #13](https://github.com/HyperdustLabs/OpenCOAT/pull/13)), `examples/02_coding_agent_demo` ([PR-12 / #14](https://github.com/HyperdustLabs/OpenCOAT/pull/14)) |
| **M3** | Persistence (sqlite + jsonl replay) | ✅ complete — `SqliteConcernStore` ([PR-13 / #15](https://github.com/HyperdustLabs/OpenCOAT/pull/15)), `SqliteDCNStore` ([PR-14 / #16](https://github.com/HyperdustLabs/OpenCOAT/pull/16)), JSONL replay ([PR-15 / #18](https://github.com/HyperdustLabs/OpenCOAT/pull/18)), `examples/03_persistent_agent_demo` ([PR-16 / #20](https://github.com/HyperdustLabs/OpenCOAT/pull/20)) |
| **M4** | Daemon + CLI + HTTP/JSON-RPC | ✅ complete — `build_runtime` ([PR-17 / #21](https://github.com/HyperdustLabs/OpenCOAT/pull/21)), in-proc JSON-RPC ([PR-18 / #22](https://github.com/HyperdustLabs/OpenCOAT/pull/22)), stdlib HTTP JSON-RPC ([PR-19 / #23](https://github.com/HyperdustLabs/OpenCOAT/pull/23)), daemon lifecycle ([PR-20 / #24](https://github.com/HyperdustLabs/OpenCOAT/pull/24)), `opencoat runtime up\|down\|status` ([PR-21 / #25](https://github.com/HyperdustLabs/OpenCOAT/pull/25)), `opencoat concern \| dcn \| inspect` ([PR-22 / #26](https://github.com/HyperdustLabs/OpenCOAT/pull/26)), `examples/06_long_running_daemon` ([PR-23 / #27](https://github.com/HyperdustLabs/OpenCOAT/pull/27)) |
| **M5** | OpenClaw host plugin | ✅ complete — event map ([#28](https://github.com/HyperdustLabs/OpenCOAT/pull/28)), injection + spans ([#29](https://github.com/HyperdustLabs/OpenCOAT/pull/29)), tool guard ([#30](https://github.com/HyperdustLabs/OpenCOAT/pull/30)), memory bridge + hooks ([#31](https://github.com/HyperdustLabs/OpenCOAT/pull/31)), `examples/04_openclaw_with_runtime` ([#32](https://github.com/HyperdustLabs/OpenCOAT/pull/32)) |
| **M6** | Heartbeat + meta governance (decay, conflict scan, merge/archive, meta-review) | ✅ complete — heartbeat workers + chat extract ([#72](https://github.com/HyperdustLabs/OpenCOAT/pull/72)), `DCNEvolver` + merge/archive + meta-review ([#73](https://github.com/HyperdustLabs/OpenCOAT/pull/73)), `examples/07_meta_governance_soak` |
| M7 | Second host (langgraph/hermes) | pending |
| M8 | Postgres + Helm/K8s | pending |

The full per-PR M1 / M2 / M3 split lives in [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Repository layout (monorepo)

```text
opencoat/
├── docs/                         # design docs, ADRs, concept guides, cookbooks
├── packages/                     # 3 PyPI packages, organised by consumer (see ADR 0009)
│   ├── opencoat-runtime-protocol/   # JSON Schemas + pydantic envelopes — the data contract
│   ├── opencoat-runtime/            # Runtime stack: core + storage + LLM + daemon + CLI
│   │   ├── opencoat_runtime_core/       # L2 pure logic: concern, joinpoint, pointcut, advice, weaving, copr, coordinator, resolver, dcn, meta, loops, ports
│   │   ├── opencoat_runtime_storage/    # ConcernStore / DCNStore backends (memory, sqlite, postgres, jsonl, vector)
│   │   ├── opencoat_runtime_llm/        # LLM / Embedder clients (openai, anthropic, azure, ollama, stub)
│   │   ├── opencoat_runtime_daemon/     # Long-running runtime: scheduler, workers, IPC, HTTP/JSON-RPC API
│   │   └── opencoat_runtime_cli/        # `opencoat` CLI: runtime up/down, concern list, replay, dcn visualize
│   └── opencoat-runtime-host/       # Host-side integration (different consumer audience)
│       ├── opencoat_runtime_host_sdk/   # Joinpoint emitter, injection consumer, transports
│       └── opencoat_runtime_host_*/     # First-party adapters (openclaw, hermes, langgraph, autogen, crewai, custom)
├── plugins/                      # out-of-tree plugin discovery (matchers, advisors, storage)
├── examples/                     # end-to-end usage examples
├── benchmarks/                   # extraction / matching / weaving benchmarks
├── tools/                        # codegen, schema check, perf dashboard
├── deploy/                       # docker-compose, kubernetes, helm, terraform
├── tests/                        # cross-package integration / e2e
└── scripts/                      # dev_up.sh, format.sh, release.sh
```

The Cursor / Codex **agent skill** (`SKILL.md`, bootstrap scripts, CDN worker) lives in [`HyperdustLabs/opencoat-skill`](https://github.com/HyperdustLabs/opencoat-skill) — it is **not** vendored under this monorepo.

Detailed layout, module breakdown, schemas, protocol, and milestones are in
[`docs/design/v0.2-system-design.md`](docs/design/v0.2-system-design.md).

---

## Quick start

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
# Install workspace + every member package in editable mode (incl. dev extras)
uv sync --all-extras --dev

# Run all tests across the workspace (≈ 440 today, all green)
uv run pytest

# Validate JSON schemas + check generated pydantic models stay in sync
uv run python tools/schema_check.py
```

### Run the M1 demo

The smallest end-to-end agent is wired up in `examples/01_simple_chat_agent/`.
It uses in-memory stores and a deterministic stub LLM, so it runs hermetically
in ≈ 50 ms with no API key required:

```bash
uv run python -m examples.01_simple_chat_agent.main

# or with your own prompts:
uv run python -m examples.01_simple_chat_agent.main \
  "Who invented OpenCOAT?" "Tell me how concerns are matched."
```

Each turn shows the matched concerns, woven injection, and verifier verdicts —
read [`examples/01_simple_chat_agent/README.md`](examples/01_simple_chat_agent/README.md)
to see what each line of the host code exercises.

### Persist concerns + DCN (M3)

[`examples/03_persistent_agent_demo/`](examples/03_persistent_agent_demo/README.md)
uses `SqliteConcernStore` and `SqliteDCNStore` on one database file and
optionally writes `session.jsonl` for `opencoat replay`:

```bash
uv run python -m examples.03_persistent_agent_demo.main
```

### Plug in a real LLM (M2)

To swap the stub for a real provider, install the matching extra and pass an
`OpenAILLMClient` (or any other adapter from `opencoat_runtime_llm`) into the
runtime:

```bash
pip install "opencoat-runtime[openai]"
export OPENAI_API_KEY=sk-...
```

```python
from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_llm import OpenAILLMClient
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

runtime = OpenCOATRuntime(
    RuntimeConfig(),
    concern_store=MemoryConcernStore(),
    dcn_store=MemoryDCNStore(),
    llm=OpenAILLMClient(model="gpt-4o-mini"),
)
```

The same client works against any OpenAI-compatible gateway (Azure, vLLM,
OpenRouter, TogetherAI, …) by setting `base_url=`. See
[`packages/opencoat-runtime/README.md`](packages/opencoat-runtime/README.md)
for the full surface.

### Run the daemon for real

For anything beyond hermetic demos you'll want a persistent daemon talking
to a real LLM. The daemon ships with `llm.provider: auto` by default — at
startup it picks the first provider whose credentials are present in the
environment:

| Env var(s)                                                | Picked      |
| --------------------------------------------------------- | ----------- |
| `OPENAI_API_KEY`                                          | `openai`    |
| `ANTHROPIC_API_KEY`                                       | `anthropic` |
| `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_DEPLOYMENT`        | `azure`     |
| _(none of the above)_                                     | `stub-fallback` (logs a WARNING — concern extraction returns 0 candidates) |

The CLI banner surfaces the chosen provider on every command so you can't
miss a degraded daemon:

```text
M4 daemon: http://127.0.0.1:7878/rpc  (status: healthy, llm: openai/gpt-4o-mini)
M4 daemon: http://127.0.0.1:7878/rpc  (status: healthy, llm: stub-fallback (degraded — no real provider wired))
```

The fastest path from "just installed" to "real provider":

```bash
# Guided (writes ~/.opencoat/daemon.yaml + ~/.opencoat/opencoat.env, then prints next steps)
opencoat configure llm
# The daemon merges allow-listed LLM keys from ~/.opencoat/opencoat.env on
# startup (before YAML is read). You do not need to `source` that file for
# `opencoat runtime up` / `python -m opencoat_runtime_daemon` to see API keys.
# Optional: `set -a && source ~/.opencoat/opencoat.env && set +a` if you want
# the same variables in your interactive shell for other tools.

# Or non-interactive / CI (wizard still writes opencoat.env; daemon reads it):
opencoat configure llm --non-interactive --provider openai --openai-api-key "$OPENAI_API_KEY"
```

Manual path (same end state if you prefer not to use the wizard):

```bash
# 1. export your provider key
export OPENAI_API_KEY=sk-...

# 2. (optional) drop a config file — only needed for non-default settings
mkdir -p ~/.opencoat
cp docs/config/daemon.yaml.example ~/.opencoat/daemon.yaml
$EDITOR ~/.opencoat/daemon.yaml      # tune paths, log level, HTTP bind, …

# 3. start the daemon — picks up the key automatically (bundled default is sqlite + HTTP)
opencoat runtime up
# or with an explicit config:
# opencoat runtime up --config ~/.opencoat/daemon.yaml

# 4. confirm the right LLM was wired
opencoat inspect joinpoints | head -1
# → M4 daemon: http://127.0.0.1:7878/rpc  (status: healthy, llm: openai/gpt-4o-mini)
```

[`docs/config/daemon.yaml.example`](docs/config/daemon.yaml.example) is a
fully annotated production sample. The complete provider knob list lives in
that file and in [`packages/opencoat-runtime/README.md`](packages/opencoat-runtime/README.md).

To force a specific provider (so the daemon refuses to start without a
key), set `llm.provider: openai` (or `anthropic` / `azure`) instead of
`auto` in the config. To deliberately run on the stub (hermetic CI,
examples) set `llm.provider: stub` — the WARNING and the banner badge
both go quiet for that explicit choice.

---

### Make the daemon long-running + persistent

The bundled daemon config persists concerns and the DCN to sqlite files under
`~/.opencoat/` and enables HTTP JSON-RPC on `127.0.0.1:7878/rpc`. On startup
the daemon reads the full concern set and activation log once to warm caches
(larger deployments can narrow this later).

Use `opencoat configure daemon` when you want to **customize** sqlite paths or
the HTTP bind address; it merges into `~/.opencoat/daemon.yaml` alongside
whatever `opencoat configure llm` wrote (either order is fine).

Start the daemon and leave it running independently of any host agent:

```bash
opencoat runtime up
# optional explicit paths — same defaults as above:
# opencoat runtime up --config ~/.opencoat/daemon.yaml --pid-file ~/.opencoat/opencoat.pid
```

`runtime up` double-forks by default so the daemon is owned by init,
not your terminal. Close the terminal, switch host-agent sessions, run
`opencoat concern …` / `opencoat inspect …` from anywhere — the daemon
just stays up. Stop it deliberately with:

```bash
opencoat runtime down
```

For **login / boot autostart** (independent of Cursor or OpenClaw), install a
user service once:

```bash
opencoat service install
opencoat service status
# opencoat service stop | start | restart
# opencoat service uninstall
```

On Linux, `systemd --user` units follow your login session; for headless
hosts use `loginctl enable-linger $USER` so the user manager runs at boot.
LLM keys are not embedded in the unit files — use `opencoat configure llm`
(inline YAML or `~/.opencoat/opencoat.env`). The daemon merges allow-listed
LLM keys from that env file at startup; add `EnvironmentFile=` only if you
need variables outside that allow-list or a non-default env file path.

### Heartbeat + DCN maintenance (M6)

With `runtime.loops.heartbeat_enabled: true` (bundled default), the daemon
starts a background scheduler (default **30s**) that calls
`OpenCOATRuntime.tick()`. Each tick runs:

| Worker | Role |
| --- | --- |
| `DecayWorker` | Bumps `activation_state.decay`; weakens / archives stale concerns |
| `MergeArchiverWorker` | Merges duplicate concerns into the DCN; archives cold `weakened` rows |
| `ConflictScannerWorker` | Writes `conflicts_with` edges for background analysis (weave-time drops stay in `ConflictResolver`) |
| `MetaReviewWorker` | Inventories `meta_concern` rows (governance capabilities) |

On startup you should see `heartbeat scheduler started` in the daemon log.
Tune overlap and cold-archive thresholds under `runtime.loops.maintenance` in
[`docs/config/daemon.yaml.example`](docs/config/daemon.yaml.example).

**Verify prerequisites** (joinpoint hot path + RPC smoke):

```bash
./scripts/verify-m6-prerequisites.sh   # daemon on 127.0.0.1:7878
```

**Hermetic soak** (10 heartbeat ticks, no 24h wait):

```bash
uv run python -m pytest packages/opencoat-runtime/tests/soak/test_heartbeat_maintenance_soak.py -q
```

See [`examples/07_meta_governance_soak/README.md`](examples/07_meta_governance_soak/README.md)
and [`docs/07-mvp/m6-conflict-paths.md`](docs/07-mvp/m6-conflict-paths.md).

**OpenClaw:** weave on user chat happens at `before_prompt_build` → `before_response`,
not on `message_received` (`on_user_input`). Optional chat mining:
`extract_from_chat` on `joinpoint.submit` or bridge config `extractOnUserMessage`
(see [`integrations/openclaw-opencoat-bridge/README.md`](integrations/openclaw-opencoat-bridge/README.md)).

---

## Contributing

All changes land via pull request — branch protection on `main` requires CI
green and a linear history. The full workflow, branching model, PR sizing,
and local verification steps are in [`CONTRIBUTING.md`](CONTRIBUTING.md), which
also tracks the per-PR breakdown for each milestone.

```bash
git switch -c feat/m2-<scope>
# ... edit ...
./scripts/verify.sh        # local mirror of CI
git push -u origin HEAD     # then open a PR on GitHub
```

---

## Concept primer

- **Concern** — first-class runtime unit. Persistable, activatable, injectable, verifiable, evolvable, relatable. The runtime only distinguishes `kind: concern | meta_concern`; semantic types (`generated_type`) are produced by LLM, not enumerated by the runtime.
- **DCN (Deep Concern Network)** — long-term graph of concerns, relations, activation history.
- **Joinpoint** — observable point in the agent's thinking pipeline (8 levels: runtime / lifecycle / message / prompt-section / span / token / structure-field / thought-unit).
- **Pointcut** — activation rule (lifecycle / role / prompt-path / keyword / regex / semantic / structure / token / claim / confidence / risk / history).
- **Advice** — guidance/constraint produced when a concern activates (11 types).
- **Weaving** — projecting advice into the host's prompt / span / token / tool / memory / output / verification / reflection layer (11 operations).
- **COPR (Concern-Oriented Prompt Representation)** — structured prompt tree replacing flat strings, so pointcuts can match at sub-message granularity.
- **Concern Vector** — sparse activation snapshot for the current turn.
- **Concern Injection** — final, host-consumable advice payload, output of weaving.

See [`docs/design/v0.1-complete-design.md`](docs/design/v0.1-complete-design.md) for the conceptual definition,
and [`docs/design/v0.2-system-design.md`](docs/design/v0.2-system-design.md) for the engineering layout.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
