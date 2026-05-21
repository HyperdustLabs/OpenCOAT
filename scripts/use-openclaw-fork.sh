#!/usr/bin/env bash
# Default OpenClaw = HyperdustLabs fork (opencoat/hooks-v0.1) at ~/openclaw-fork.
# Global npm install and gateway LaunchAgent must be 1:1 with that tree.
#
# Usage:
#   ./scripts/use-openclaw-fork.sh              # bind CLI + gateway to existing fork
#   ./scripts/use-openclaw-fork.sh --clone      # git clone fork first
#   ./scripts/use-openclaw-fork.sh --update     # git pull + pnpm install + rebuild
#   ./scripts/use-openclaw-fork.sh --build      # pnpm build only (no git pull)
#   ./scripts/use-openclaw-fork.sh --check      # verify 1:1 (same as check-openclaw-fork.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORK_ROOT="${OPENCLAW_FORK_ROOT:-$HOME/openclaw-fork}"
FORK_REPO="${OPENCLAW_FORK_REPO:-https://github.com/HyperdustLabs/openclaw.git}"
FORK_BRANCH="${OPENCLAW_FORK_BRANCH:-opencoat/hooks-v0.1}"
LOCAL_BIN="${HOME}/.local/bin"
SHIM="${LOCAL_BIN}/openclaw-fork"
LOCK="${HOME}/.openclaw/openclaw-fork.json"

clone=false
update=false
build=false
check=false
for arg in "$@"; do
  case "$arg" in
    --clone) clone=true ;;
    --update) update=true; build=true ;;
    --build) build=true ;;
    --check) check=true ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$check" == true ]]; then
  exec "${ROOT}/scripts/check-openclaw-fork.sh"
fi

if [[ "$clone" == true && ! -d "$FORK_ROOT/.git" ]]; then
  git clone --branch "$FORK_BRANCH" "$FORK_REPO" "$FORK_ROOT"
fi

if [[ ! -d "$FORK_ROOT" ]]; then
  echo "missing $FORK_ROOT — run with --clone or set OPENCLAW_FORK_ROOT" >&2
  exit 1
fi

if [[ "$update" == true ]]; then
  git -C "$FORK_ROOT" fetch origin "$FORK_BRANCH"
  git -C "$FORK_ROOT" checkout "$FORK_BRANCH"
  git -C "$FORK_ROOT" pull --ff-only origin "$FORK_BRANCH" || true
fi

if [[ ! -d "$FORK_ROOT/node_modules" ]] || [[ "$update" == true ]]; then
  (cd "$FORK_ROOT" && (command -v pnpm >/dev/null && pnpm install || npm install))
fi

if [[ "$build" == true ]] || [[ ! -f "$FORK_ROOT/dist/index.js" ]]; then
  echo "building openclaw-fork..."
  (cd "$FORK_ROOT" && (command -v pnpm >/dev/null && pnpm build || npm run build))
fi

if [[ ! -f "$FORK_ROOT/dist/index.js" ]]; then
  echo "build failed — dist/index.js missing under $FORK_ROOT" >&2
  exit 1
fi

# Remove registry/global copies that are not the fork (avoid version drift).
if command -v npm >/dev/null; then
  npm_global="$(npm root -g 2>/dev/null)/openclaw"
  if [[ -e "$npm_global" && ! -L "$npm_global" ]]; then
    echo "removing non-symlink npm global openclaw (registry copy)..."
    npm uninstall -g openclaw 2>/dev/null || true
  fi
  echo "linking npm -g openclaw -> $FORK_ROOT"
  (cd "$FORK_ROOT" && npm install -g .)
fi

mkdir -p "$LOCAL_BIN" "${HOME}/.openclaw"
cat >"$SHIM" <<EOF
#!/usr/bin/env bash
# OpenClaw fork CLI — 1:1 with ${FORK_ROOT}
set -euo pipefail
OPENCLAW_FORK_ROOT="\${OPENCLAW_FORK_ROOT:-$FORK_ROOT}"
exec "\${OPENCLAW_FORK_NODE:-\$(command -v node)}" "\$OPENCLAW_FORK_ROOT/openclaw.mjs" "\$@"
EOF
chmod +x "$SHIM"

if [[ -f "${LOCAL_BIN}/openclaw" ]] && grep -qE 'BAIclaw|/Applications/' "${LOCAL_BIN}/openclaw" 2>/dev/null; then
  rm -f "${LOCAL_BIN}/openclaw"
fi
ln -sf "$SHIM" "${LOCAL_BIN}/openclaw"

commit="$(git -C "$FORK_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
commit_short="$(git -C "$FORK_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
version="$(node "$FORK_ROOT/openclaw.mjs" --version 2>/dev/null || echo unknown)"
installed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

python3 - "$LOCK" <<PY
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    "fork_root": "${FORK_ROOT}",
    "branch": "${FORK_BRANCH}",
    "commit": "${commit}",
    "commit_short": "${commit_short}",
    "version": "${version}".strip(),
    "npm_global": "symlink via npm install -g .",
    "shim": "${SHIM}",
    "installed_at": "${installed_at}",
}, indent=2) + "\n")
path.chmod(0o600)
PY

if command -v openclaw >/dev/null; then
  openclaw config validate
  openclaw gateway install --force
  openclaw daemon restart || true
fi

echo ""
echo "OpenClaw fork is now the default (1:1 with ${FORK_ROOT})"
echo "  version: ${version}"
echo "  commit:  ${commit_short} (${FORK_BRANCH})"
echo "  lock:    ${LOCK}"
echo ""
"${ROOT}/scripts/check-openclaw-fork.sh"
