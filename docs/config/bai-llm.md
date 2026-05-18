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
