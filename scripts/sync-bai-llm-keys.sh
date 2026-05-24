#!/usr/bin/env bash
# Sync B.AI API key to OpenCOAT (~/.opencoat/opencoat.env + daemon.yaml) and
# OpenClaw (auth-profiles.json). Requires BAI_API_KEY in the environment, or
# an existing key in opencoat.env (use --from-env-file to prefer the file).
set -euo pipefail

OPENCOAT_ENV="${HOME}/.opencoat/opencoat.env"
DAEMON_YAML="${HOME}/.opencoat/daemon.yaml"
OPENCLAW_AUTH="${HOME}/.openclaw/agents/main/agent/auth-profiles.json"
FROM_FILE=false

usage() {
  echo "Usage: BAI_API_KEY=sk-... $0" >&2
  echo "   or: $0 --from-env-file   # use key already in ~/.opencoat/opencoat.env" >&2
  exit 2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
fi
if [[ "${1:-}" == "--from-env-file" ]]; then
  FROM_FILE=true
fi

read_env_key() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    sys.exit(0)
for line in path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    if k.strip() == "BAI_API_KEY":
        print(v.strip().strip('"').strip("'"))
        break
PY
}

KEY="${BAI_API_KEY:-}"
if [[ -z "${KEY}" || "${FROM_FILE}" == true ]]; then
  FILE_KEY="$(read_env_key "${OPENCOAT_ENV}")"
  if [[ -n "${FILE_KEY}" ]]; then
    KEY="${FILE_KEY}"
  fi
fi
if [[ -z "${KEY}" ]]; then
  echo "sync-bai-llm-keys: set BAI_API_KEY in the shell or in ${OPENCOAT_ENV}" >&2
  usage
fi

mkdir -p "$(dirname "${OPENCOAT_ENV}")"
python3 - "${OPENCOAT_ENV}" "${KEY}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
lines: list[str] = []
found = False
if path.is_file():
    for line in path.read_text().splitlines():
        if line.strip().startswith("BAI_API_KEY="):
            lines.append(f"BAI_API_KEY={key}")
            found = True
        elif line.strip().startswith("OPENAI_API_KEY="):
            lines.append(f"# {line}  # disabled — using B.AI")
        else:
            lines.append(line)
if not found:
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"BAI_API_KEY={key}")
header = """# OpenCOAT daemon LLM credentials — chmod 600; do not commit.
# Load before `opencoat runtime up`:
#   set -a && source ~/.opencoat/opencoat.env && set +a

"""
if not lines:
    path.write_text(header + f"BAI_API_KEY={key}\n")
else:
    text = "\n".join(lines)
    if not text.startswith("#"):
        text = header + text
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text)
path.chmod(0o600)
PY

if command -v opencoat >/dev/null 2>&1; then
  opencoat configure llm --non-interactive \
    --provider bai \
    --model gpt-5.2 \
    --mode env-file \
    --bai-api-key "${KEY}" \
    --timeout 30
else
  echo "sync-bai-llm-keys: opencoat CLI not found — skipped configure llm" >&2
fi

python3 - "${OPENCLAW_AUTH}" "${KEY}" <<'PY'
import json
import sys
from pathlib import Path

auth_path = Path(sys.argv[1])
key = sys.argv[2]
auth_path.parent.mkdir(parents=True, exist_ok=True)
data = json.loads(auth_path.read_text()) if auth_path.is_file() else {"version": 1, "profiles": {}}
profiles = data.setdefault("profiles", {})
profiles["openai:default"] = {
    "type": "api_key",
    "provider": "openai",
    "key": key,
}
auth_path.write_text(json.dumps(data, indent=2) + "\n")
auth_path.chmod(0o600)
PY

echo "sync-bai-llm-keys: updated ${OPENCOAT_ENV} and ${OPENCLAW_AUTH}"
echo "sync-bai-llm-keys: restart: opencoat runtime down && opencoat runtime up && openclaw daemon restart"
