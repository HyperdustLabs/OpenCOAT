# B.AI LLM provider

OpenCOAT talks to [B.AI](https://docs.b.ai/llmservice/api/) via the OpenAI-compatible
`POST /v1/chat/completions` endpoint at `https://api.b.ai/v1`.

## Quick setup

```bash
export BAI_API_KEY='sk-...'   # platform-issued key from B.AI

# Interactive wizard (writes ~/.opencoat/opencoat.env + daemon.yaml)
opencoat configure llm
# Choose provider [2] b.ai

# Or pin explicitly in ~/.opencoat/daemon.yaml:
# llm:
#   provider: bai
#   model: gpt-5.2

opencoat runtime up
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `BAI_API_KEY` | API key (`Authorization: Bearer` or same value as `x-api-key`) |
| `BAI_BASE_URL` | Override base URL (default `https://api.b.ai/v1`) |
| `BAI_MODEL` | Default model when `llm.provider` is `auto` and B.AI is selected |

With `llm.provider: auto`, probe order is **B.AI → OpenAI → Anthropic → Azure**.

## Verify

```bash
./scripts/verify-m6-prerequisites.sh   # unrelated to B.AI; optional health check

curl -sS https://api.b.ai/v1/models \
  -H "Authorization: Bearer $BAI_API_KEY" | python3 -m json.tool
```

Hermetic tests: `uv run pytest packages/opencoat-runtime/tests/llm/test_bai_client.py`.

## OpenClaw + B.AI

Use the same B.AI key for **two** runtimes on one machine:

| Component | Role | B.AI usage |
| --- | --- | --- |
| **OpenCOAT daemon** (`opencoat runtime up`, `:7878`) | Concern extract, advice, weaving | `llm.provider: bai` in `~/.opencoat/daemon.yaml` |
| **OpenClaw gateway** (Telegram / CLI chat) | End-user agent turns | `models.providers.openai` pointed at `https://api.b.ai/v1` |
| **OpenCOAT bridge** ([`integrations/openclaw-opencoat-bridge/`](../../integrations/openclaw-opencoat-bridge/README.md)) | Forwards hooks → `joinpoint.submit` | No LLM calls — only HTTP to the daemon |

The bridge does **not** read `BAI_API_KEY`. Chat LLM and daemon LLM are configured independently; keeping the same model id (e.g. `gpt-5.2`) avoids mismatched behavior between extraction and replies.

### 1. OpenCOAT daemon (concern / DCN path)

```bash
export BAI_API_KEY='sk-...'   # or write to ~/.opencoat/opencoat.env

opencoat configure llm          # provider [2] b.ai, model e.g. gpt-5.2
opencoat runtime up
opencoat runtime llm_info       # expect bai/gpt-5.2, real: true
```

### 2. OpenClaw chat LLM (B.AI via OpenAI-compatible provider)

OpenClaw still uses the provider id `openai`, but requests go to B.AI when `baseUrl` is overridden.

**Recommended:** install the bridge, then apply B.AI provider override + auth in one step (reads `~/.opencoat/opencoat.env`):

```bash
# From COAT repo root
openclaw plugins install -l integrations/openclaw-opencoat-bridge

python3 <<'PY'
import json
from pathlib import Path

def parse_env(path):
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out

env = parse_env(Path.home() / ".opencoat/opencoat.env")
key = env.get("BAI_API_KEY")
if not key:
    raise SystemExit("BAI_API_KEY missing in ~/.opencoat/opencoat.env")

auth_path = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
auth = json.loads(auth_path.read_text())
auth.setdefault("profiles", {})["openai:default"] = {
    "type": "api_key",
    "provider": "openai",
    "key": key,
}
auth_path.write_text(json.dumps(auth, indent=2) + "\n")

cfg_path = Path.home() / ".openclaw/openclaw.json"
cfg = json.loads(cfg_path.read_text())
cfg.setdefault("models", {}).setdefault("providers", {})["openai"] = {
    "baseUrl": env.get("BAI_BASE_URL", "https://api.b.ai/v1"),
    "api": "openai-completions",
    "auth": "api-key",
    "models": [
        {"id": "gpt-5.2", "name": "B.AI gpt-5.2", "api": "openai-completions", "input": ["text", "image"], "contextWindow": 200000},
        {"id": "gpt-5.4", "name": "B.AI gpt-5.4", "api": "openai-completions", "input": ["text", "image"], "contextWindow": 266000},
    ],
}
defaults = cfg.setdefault("agents", {}).setdefault("defaults", {})
defaults.setdefault("models", {})["openai/gpt-5.2"] = {"alias": "bai-primary"}
defaults.setdefault("model", {})["primary"] = "openai/gpt-5.2"
cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
print("OpenClaw: auth-profiles + models.providers.openai -> B.AI, primary openai/gpt-5.2")
PY

openclaw config validate
openclaw daemon restart
```

Do not set `models.providers.openai` field-by-field with `openclaw config set` on an empty provider — validation requires the full `models[]` array. See [`daemon.yaml.example`](daemon.yaml.example) for the OpenCOAT daemon side.

**LaunchAgent / gateway service:** do **not** set `models.providers.openai.apiKey` to `{ "source": "env", "id": "BAI_API_KEY" }` unless `BAI_API_KEY` is injected into the gateway process (e.g. LaunchAgent `EnvironmentVariables`). A missing env var makes the gateway refuse to start. Prefer **`auth-profiles.json`** (`openai:default`) as above.

After restart:

```bash
openclaw models status          # Default: openai/gpt-5.2
openclaw agent --agent main --message "Reply with exactly: BAI_OK"
grep opencoat-bridge ~/.openclaw/logs/gateway.log   # [opencoat-bridge] registered
```

### 3. Concerns + live host

```bash
opencoat concern import --demo
# Telegram / TUI: send a message that matches a concern keyword
curl -sS http://127.0.0.1:7878/rpc -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"dcn.activation_log","params":{"limit":10},"id":1}' \
  | python3 -m json.tool
```

Full bridge checklist (message-level joinpoints, `#msg:N` in DCN): [bridge README § Verify](../../integrations/openclaw-opencoat-bridge/README.md#verify).

### Rotating the B.AI key

1. Update `BAI_API_KEY` in `~/.opencoat/opencoat.env`.
2. `opencoat runtime down && opencoat runtime up` (daemon reloads env).
3. Re-run the auth-profile sync snippet (or `openclaw models auth paste-token --provider openai`).
4. `openclaw daemon restart`.
