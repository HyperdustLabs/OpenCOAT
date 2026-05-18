"""Layered config loader.

Precedence (high → low):

    CLI flags  >  environment (OPENCOAT_*)  >  user config file  >  bundled default

The loader returns a strongly-typed :class:`DaemonConfig` that bundles the
runtime config and the operational settings (storage / LLM / IPC).
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from opencoat_runtime_core.config import RuntimeConfig
from pydantic import BaseModel, ConfigDict, Field


class StorageBackend(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: str


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concern_store: StorageBackend = StorageBackend(kind="memory")
    dcn_store: StorageBackend = StorageBackend(kind="memory")


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    # Default ``auto`` so a zero-config daemon picks the operator's
    # real provider whenever one is available, and only falls back to
    # stub (with a loud warning) when no credentials are present. See
    # :func:`opencoat_runtime_daemon.runtime_builder._build_auto` for
    # the probe order.
    provider: str = "auto"
    timeout_seconds: float = 20.0


class IPCEndpoint(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False


class IPCSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inproc: IPCEndpoint = IPCEndpoint(enabled=True)
    unix_socket: IPCEndpoint = IPCEndpoint(enabled=False)
    http: IPCEndpoint = IPCEndpoint(enabled=False)
    grpc: IPCEndpoint = IPCEndpoint(enabled=False)


class ObservabilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log_level: str = "INFO"
    otel_endpoint: str | None = None


class PluginSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hosts: list[str] = Field(default_factory=list)
    matchers: list[str] = Field(default_factory=list)
    advisors: list[str] = Field(default_factory=list)


class DaemonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ipc: IPCSettings = Field(default_factory=IPCSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    plugins: PluginSettings = Field(default_factory=PluginSettings)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# Keys ``merge_user_llm_env_file`` may pull from ``~/.opencoat/opencoat.env``.
# Keep this aligned with :mod:`opencoat_runtime_daemon.runtime_builder`
# (LLM credential / endpoint resolution) and ``opencoat configure llm``.
# Arbitrary keys are rejected so the env file cannot flip unrelated daemon
# toggles (e.g. ``OPENCOAT_TEST_MEMORY_STORES``).
_MERGEABLE_OPENCOAT_ENV_KEYS: frozenset[str] = frozenset(
    {
        "BAI_API_KEY",
        "BAI_BASE_URL",
        "BAI_MODEL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_ENDPOINT",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "OPENAI_API_VERSION",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENCOAT_AZURE_DEPLOYMENT",
    }
)


def merge_user_llm_env_file() -> None:
    """Load ``~/.opencoat/opencoat.env`` into :data:`os.environ` (``setdefault`` only).

    ``opencoat configure llm`` writes provider API keys to this file.
    Detached daemons (the default ``opencoat runtime up``) only inherit
    the spawning process's environment — operators often forget to
    ``source`` the file first.  Merging here makes the wizard's env-file
    mode work without an extra shell step.  Keys already present in the
    process environment win (explicit ``export`` / launchd overrides).

    Only a fixed allow-list of LLM-related variable names is merged;
    other entries in the file are ignored so the file cannot act as a
    generic config-injection channel.
    """
    path = Path.home() / ".opencoat" / "opencoat.env"
    if not path.is_file():
        return
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in raw_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key or key not in _MERGEABLE_OPENCOAT_ENV_KEYS:
            continue
        val = val.strip().strip('"').strip("'")
        if not val:
            continue
        os.environ.setdefault(key, val)


def resolve_daemon_config_path(explicit: Path | None) -> Path | None:
    """Config file path for daemon / CLI when ``--config`` is omitted.

    ``opencoat configure llm`` writes ``~/.opencoat/daemon.yaml``.  Runtime
    commands use that file automatically when it exists so operators are not
    required to pass ``--config`` on every ``runtime up``.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    user = Path.home() / ".opencoat" / "daemon.yaml"
    return user if user.is_file() else None


def load_config(path: Path | None = None) -> DaemonConfig:
    """Load and validate the daemon config.

    Always starts from the bundled ``default.yaml`` and overlays the user's
    file (if any) on top.  Env / CLI overlays land at M4.

    Pass an explicit ``path`` (or call :func:`resolve_daemon_config_path`
    first) to load ``~/.opencoat/daemon.yaml``.  ``load_config()`` with no
    argument loads only the bundled defaults — used by hermetic tests.
    """
    bundled = files("opencoat_runtime_daemon.config").joinpath("default.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(bundled) or {}

    if path is not None:
        user = _read_yaml(Path(path))
        data = _merge(data, user)

    # Hermetic pytest / CI only — forces in-process stores so parallel
    # ``pytest`` workers never fight over ``~/.opencoat/*.sqlite``. Never
    # set in production; see ``packages/opencoat-runtime/tests/conftest.py``.
    if os.environ.get("OPENCOAT_TEST_MEMORY_STORES") == "1":
        data = _merge(
            data,
            {
                "storage": {
                    "concern_store": {"kind": "memory"},
                    "dcn_store": {"kind": "memory"},
                }
            },
        )

    return DaemonConfig.model_validate(data)


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict overlay — ``b`` wins on conflict."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out
