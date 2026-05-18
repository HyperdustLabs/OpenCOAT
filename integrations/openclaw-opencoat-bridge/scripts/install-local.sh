#!/usr/bin/env bash
# Install the OpenCOAT OpenClaw bridge into ~/.openclaw/extensions and merge
# a plugins.entries stub into openclaw.json (idempotent-ish).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Plugin id in config uses @scope/name; filesystem dir must not contain '/'.
EXT_ID="@hyperdustlabs/opencoat-bridge"
INSTALL_DIR="${HOME}/.openclaw/extensions/@hyperdustlabs-opencoat-bridge"
CONFIG="${HOME}/.openclaw/openclaw.json"

echo "Building bridge at ${ROOT}..."
(cd "${ROOT}" && npm install && npm run build)

mkdir -p "$(dirname "${INSTALL_DIR}")"
if [[ -e "${INSTALL_DIR}" && ! -L "${INSTALL_DIR}" ]]; then
  echo "Removing existing ${INSTALL_DIR}"
  rm -rf "${INSTALL_DIR}"
fi
ln -sfn "${ROOT}" "${INSTALL_DIR}"
echo "Linked ${INSTALL_DIR} -> ${ROOT}"

if [[ ! -f "${CONFIG}" ]]; then
  echo "No ${CONFIG} — add plugins.entries.${EXT_ID} manually (see README)."
  exit 0
fi

export ROOT EXT_ID INSTALL_DIR CONFIG
python3 <<'PY'
import json
import os
from pathlib import Path

config_path = Path(os.environ["CONFIG"])
data = json.loads(config_path.read_text())
plugins = data.setdefault("plugins", {})
entries = plugins.setdefault("entries", {})
installs = plugins.setdefault("installs", {})

for stale in ("@hyperdust/opencoat-bridge", "@hyperdust-opencoat-bridge"):
    entries.pop(stale, None)
    installs.pop(stale, None)

entries[os.environ["EXT_ID"]] = {
    "enabled": True,
    "hooks": {"allowPromptInjection": True},
    "config": {
        "daemonUrl": os.environ.get("OPENCOAT_DAEMON_URL", "http://127.0.0.1:7878/rpc"),
        "logActivations": True,
    },
}
installs[os.environ["EXT_ID"]] = {
    "source": "path",
    "sourcePath": os.environ["ROOT"],
    "installPath": os.environ["INSTALL_DIR"],
    "version": "0.1.0",
}
config_path.write_text(json.dumps(data, indent=2) + "\n")
print(f"Updated {config_path} — enable {os.environ['EXT_ID']} and restart the gateway.")
PY

echo "Done. Restart OpenClaw gateway, then send a user message and check dcn.activation_log."
