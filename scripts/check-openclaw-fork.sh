#!/usr/bin/env bash
# Verify global `openclaw` + gateway service are 1:1 with ~/openclaw-fork.
set -euo pipefail

FORK_ROOT="${OPENCLAW_FORK_ROOT:-$HOME/openclaw-fork}"
LOCK="${HOME}/.openclaw/openclaw-fork.json"
FAIL=0

say_ok() { printf '  ok  %s\n' "$1"; }
say_bad() { printf '  FAIL %s\n' "$1"; FAIL=1; }

echo "OpenClaw fork alignment (expected root: ${FORK_ROOT})"

if [[ ! -d "$FORK_ROOT/.git" ]]; then
  say_bad "fork repo missing: $FORK_ROOT (.git)"
else
  commit="$(git -C "$FORK_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"
  branch="$(git -C "$FORK_ROOT" branch --show-current 2>/dev/null || echo '?')"
  say_ok "fork git ${branch} @ ${commit}"
fi

if [[ ! -f "$FORK_ROOT/openclaw.mjs" || ! -f "$FORK_ROOT/dist/index.js" ]]; then
  say_bad "fork not built — run: cd $FORK_ROOT && pnpm install && pnpm build"
else
  fork_ver="$(node "$FORK_ROOT/openclaw.mjs" --version 2>/dev/null || true)"
  say_ok "fork CLI: ${fork_ver:-unknown}"
fi

if ! command -v openclaw >/dev/null; then
  say_bad "openclaw not on PATH"
else
  cli_path="$(command -v openclaw)"
  cli_ver="$(openclaw --version 2>/dev/null || true)"
  say_ok "PATH openclaw: ${cli_ver:-?} (${cli_path})"
fi

if command -v npm >/dev/null; then
  npm_pkg="$(npm root -g 2>/dev/null)/openclaw"
  if [[ -e "$npm_pkg" ]]; then
    if [[ -L "$npm_pkg" ]]; then
      resolved="$(cd "$npm_pkg" 2>/dev/null && pwd -P || true)"
      if [[ "$resolved" == "$FORK_ROOT" ]]; then
        say_ok "npm -g openclaw resolves to fork (${resolved})"
      else
        say_bad "npm -g openclaw resolves to ${resolved:-?}, want ${FORK_ROOT}"
      fi
    else
      say_bad "npm -g openclaw is a copy, not symlink — run: ./scripts/use-openclaw-fork.sh"
    fi
  else
    say_bad "npm -g openclaw not installed — run: ./scripts/use-openclaw-fork.sh"
  fi
fi

if command -v openclaw >/dev/null; then
  gw_cmd="$(openclaw gateway status 2>/dev/null | awk -F': ' '/^Command:/{print $2; exit}' || true)"
  if [[ "$gw_cmd" == *"$FORK_ROOT/dist/index.js"* ]]; then
    say_ok "gateway service uses fork dist"
  elif [[ -n "$gw_cmd" ]]; then
    say_bad "gateway not on fork: ${gw_cmd}"
  else
    say_bad "gateway status unavailable — is LaunchAgent running?"
  fi
  cli_gw="$(openclaw gateway status 2>/dev/null | awk -F': ' '/^CLI version:|^Gateway version:/{print $2}' | tr '\n' ' ' || true)"
  if [[ -n "$cli_gw" ]]; then
    say_ok "versions: ${cli_gw}"
  fi
fi

if [[ -f "$LOCK" ]]; then
  say_ok "lock file: $LOCK"
else
  say_bad "missing lock file — run: ./scripts/use-openclaw-fork.sh"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "All checks passed — global openclaw is 1:1 with fork."
else
  echo "Fix with: ./scripts/use-openclaw-fork.sh [--update] [--build]" >&2
  exit 1
fi
