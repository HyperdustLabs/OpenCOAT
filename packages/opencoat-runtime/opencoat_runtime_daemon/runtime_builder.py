"""Build a wired :class:`OpenCOATRuntime` from a :class:`DaemonConfig` (M4 PR-17).

The daemon, the CLI's in-proc smoke harness, and every later M4 IPC
endpoint all want the **same** runtime out of the same config — so we
keep that wiring in one place instead of letting it drift between
``daemon.py``, ``__main__.py``, and the host examples.

Inputs (high → low precedence):

1. ``DaemonConfig`` — typed, already overlaid with the user's YAML.
2. ``env`` — process environment mapping (defaults to :data:`os.environ`)
   used **only** for LLM provider credentials. Storage paths come
   from the config, not the env.

Outputs:

* :class:`BuiltRuntime` — bundles the live :class:`OpenCOATRuntime`, the
  resolved provider label, and a ``close()`` callable the caller invokes
  on shutdown so sqlite connections aren't leaked. The future
  :class:`~opencoat_runtime_daemon.daemon.Daemon` calls this at startup and
  routes ``close()`` from its drain handler.

Supported backends:

* Storage: ``sqlite`` (bundled default under ``~/.opencoat/``) and
  ``memory`` (hermetic tests / embedded). Both stores accept ``:memory:``
  and treat the empty / missing path as in-memory.
* LLM: ``auto`` (default — picks the first provider whose credentials
  are present in the environment, falling back to a stub with a loud
  startup warning), plus the explicit providers ``stub`` /
  ``openai`` / ``anthropic`` / ``azure``. Real-provider construction
  is hermetic in CI because the providers' SDKs are only imported when
  the matching ``provider`` is chosen.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_core.ports import ConcernStore, DCNStore, LLMClient
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore
from opencoat_runtime_storage.sqlite import SqliteConcernStore, SqliteDCNStore

from .config.loader import DaemonConfig, LLMSettings, StorageBackend

logger = logging.getLogger(__name__)

_STUB_DEFAULT_CHAT = (
    "(stub) OpenCOAT daemon runtime is wired up. Set BAI_API_KEY / OPENAI_API_KEY / "
    "ANTHROPIC_API_KEY / AZURE_OPENAI_ENDPOINT (and friends) and "
    "switch the daemon's llm.provider to a real provider to see a "
    "real answer here. See https://docs.python.org/3/ [1]."
)

# Surfaced verbatim in the daemon log, the CLI banner status line, and
# every ``runtime.llm_info`` RPC response when ``provider: auto`` could
# not find any real-provider credentials. Worded as a direct fix-it
# instruction so users don't bounce between docs.
_STUB_FALLBACK_HINT = (
    "no provider credentials detected — concern extraction and any "
    "other LLM-driven path will return empty results. Fix by exporting "
    "BAI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / AZURE_OPENAI_* before "
    "restarting the daemon, or pin llm.provider in your daemon config."
)

_DEFAULT_BAI_MODEL = "gpt-5.2"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
_DEFAULT_AZURE_API_VERSION = "2024-10-21"


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LLMInfo:
    """Structured description of the LLM the runtime ended up wired with.

    Exposed verbatim by the ``runtime.llm_info`` JSON-RPC method and the
    CLI banner so users immediately see whether the daemon is talking
    to a real provider or running on the stub fallback.

    Attributes
    ----------
    label:
        Human-friendly identifier (``"openai/gpt-4o-mini"``,
        ``"anthropic/claude-3-5-haiku-latest"``, ``"stub"``,
        ``"stub-fallback"``).
    kind:
        Coarse classification — ``"bai" | "openai" | "anthropic" | "azure" |
        "stub"``. Stays stable across model upgrades, so callers
        branching on "is this a real LLM?" can do
        ``kind != "stub"`` instead of parsing ``label``.
    real:
        ``True`` whenever the LLM is one of the real providers,
        ``False`` for any stub variant. Pure convenience over
        ``kind``.
    requested:
        The provider value the daemon config asked for verbatim —
        ``"auto"`` when auto-detection chose the actual provider,
        otherwise the same as ``kind``.
    hint:
        Optional human-readable fix-it line; non-empty only when the
        daemon fell back to stub (or otherwise degraded). Empty
        string on the happy path.
    """

    label: str
    kind: str
    real: bool
    requested: str
    hint: str = ""


@dataclass
class BuiltRuntime:
    """Configured :class:`OpenCOATRuntime` plus the resources backing it.

    ``close()`` is idempotent and closes any sqlite handles that the
    builder opened. Memory backends ignore it.
    """

    runtime: OpenCOATRuntime
    llm_label: str
    llm_info: LLMInfo
    closers: list[Callable[[], None]] = field(default_factory=list)
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fn in self.closers:
            fn()

    def __enter__(self) -> BuiltRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_runtime(
    config: DaemonConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> BuiltRuntime:
    """Construct a :class:`OpenCOATRuntime` wired per ``config``.

    When ``env`` is left as ``None`` the builder resolves credentials and
    optional knobs from :data:`os.environ` and lets each provider SDK
    consult its own documented env fallbacks for anything we don't pass
    through.

    When the caller passes ``env`` explicitly, the builder treats that
    mapping as the **only** environment source: credentials missing from
    both the config and the injected mapping raise loudly instead of
    silently falling back to :data:`os.environ`. This keeps tests and
    embedded uses hermetic (Codex P1 on PR-17).
    """
    env_explicit = env is not None
    resolved_env: Mapping[str, str] = env if env is not None else os.environ
    closers: list[Callable[[], None]] = []

    concern_store = _build_concern_store(config.storage.concern_store, closers)
    dcn_store = _build_dcn_store(config.storage.dcn_store, closers)
    llm, info = _build_llm(config.llm, resolved_env, env_explicit=env_explicit)

    if not info.real and info.hint:
        # Loud-warn whenever we fell back to stub so the operator
        # never has to ask "why is concern extraction returning 0
        # candidates?". This is the single moment that
        # ``opencoat runtime up`` could plausibly look healthy while
        # silently degrading every LLM-driven path.
        logger.warning("OpenCOAT LLM provider degraded to %s — %s", info.label, info.hint)

    runtime = OpenCOATRuntime(
        config.runtime,
        concern_store=concern_store,
        dcn_store=dcn_store,
        llm=llm,
    )
    return BuiltRuntime(
        runtime=runtime,
        llm_label=info.label,
        llm_info=info,
        closers=closers,
    )


def warm_persistent_stores(runtime: OpenCOATRuntime) -> None:
    """Sequential scan of stores to warm sqlite page cache without O(n) RAM.

    We iterate and discard each row so peak memory stays bounded by one
    deserialized object at a time. ``list(iter_all())`` would materialize
    every concern and activation at daemon start and could OOM or push
    ``runtime up`` past its health deadline on large datasets (Codex P1).
    """
    concern_count = 0
    for _ in runtime.concern_store.iter_all():
        concern_count += 1
    activation_count = 0
    for _ in runtime.dcn_store.activation_log(None, limit=None):
        activation_count += 1
    logger.info(
        "OpenCOAT store warm-up complete (concerns=%d dcn_activations=%d)",
        concern_count,
        activation_count,
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _backend_extras(spec: StorageBackend) -> dict[str, Any]:
    return spec.model_dump(exclude={"kind"})


def _resolve_sqlite_path(extras: dict[str, Any]) -> str:
    raw = extras.get("path")
    if raw is None or raw == "" or raw == ":memory:":
        return ":memory:"
    return str(Path(raw).expanduser())


def _build_concern_store(
    spec: StorageBackend,
    closers: list[Callable[[], None]],
) -> ConcernStore:
    kind = spec.kind.lower()
    if kind == "memory":
        return MemoryConcernStore()
    if kind == "sqlite":
        store = SqliteConcernStore(_resolve_sqlite_path(_backend_extras(spec)))
        closers.append(store.close)
        return store
    raise ValueError(f"Unknown concern_store backend kind={spec.kind!r}")


def _build_dcn_store(
    spec: StorageBackend,
    closers: list[Callable[[], None]],
) -> DCNStore:
    kind = spec.kind.lower()
    if kind == "memory":
        return MemoryDCNStore()
    if kind == "sqlite":
        store = SqliteDCNStore(_resolve_sqlite_path(_backend_extras(spec)))
        closers.append(store.close)
        return store
    raise ValueError(f"Unknown dcn_store backend kind={spec.kind!r}")


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


_LlmBuilder = Callable[
    [LLMSettings, Mapping[str, str], bool],
    "tuple[LLMClient, LLMInfo]",
]


def _build_stub(
    settings: LLMSettings,
    _env: Mapping[str, str],
    _env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    return (
        StubLLMClient(default_chat=_STUB_DEFAULT_CHAT),
        LLMInfo(
            label="stub",
            kind="stub",
            real=False,
            requested=settings.provider,
            # Explicit ``provider: stub`` is a deliberate choice
            # (hermetic tests, examples, M1 happy path) — don't
            # nag the operator about it.
            hint="",
        ),
    )


def _llm_extras(settings: LLMSettings) -> dict[str, Any]:
    return settings.model_dump(exclude={"provider", "timeout_seconds"})


def _require_explicit(
    provider: str,
    field_name: str,
    env_var: str,
    *,
    env_explicit: bool,
) -> None:
    """Raise when ``env`` was passed explicitly but a required credential is missing.

    Codex P1 on PR-17: passing ``api_key=None`` (etc.) to the underlying
    SDK lets it transparently consult :data:`os.environ`, which breaks
    the hermetic ``env=`` contract callers explicitly opted into.
    """
    if not env_explicit:
        return
    raise RuntimeError(
        f"llm.provider={provider} but {field_name!r} is missing from both "
        f"the daemon config and the injected env mapping (looked for "
        f"{env_var}). Refusing to fall back to os.environ because "
        f"build_runtime(env=...) was passed explicitly."
    )


def _build_bai(
    settings: LLMSettings,
    env: Mapping[str, str],
    env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    from opencoat_runtime_llm import BaiLLMClient

    extras = _llm_extras(settings)
    model = extras.get("model") or env.get("BAI_MODEL") or _DEFAULT_BAI_MODEL
    api_key = extras.get("api_key") or env.get("BAI_API_KEY")
    if not api_key:
        _require_explicit("bai", "api_key", "BAI_API_KEY", env_explicit=env_explicit)
    base_url = extras.get("base_url") or env.get("BAI_BASE_URL")
    return (
        BaiLLMClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=settings.timeout_seconds,
        ),
        LLMInfo(
            label=f"bai/{model}",
            kind="bai",
            real=True,
            requested=settings.provider,
        ),
    )


def _build_openai(
    settings: LLMSettings,
    env: Mapping[str, str],
    env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    from opencoat_runtime_llm import OpenAILLMClient

    extras = _llm_extras(settings)
    model = extras.get("model") or env.get("OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL
    api_key = extras.get("api_key") or env.get("OPENAI_API_KEY")
    if not api_key:
        _require_explicit("openai", "api_key", "OPENAI_API_KEY", env_explicit=env_explicit)
    base_url = extras.get("base_url") or env.get("OPENAI_BASE_URL") or env.get("OPENAI_API_BASE")
    return (
        OpenAILLMClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=settings.timeout_seconds,
        ),
        LLMInfo(
            label=f"openai/{model}",
            kind="openai",
            real=True,
            requested=settings.provider,
        ),
    )


def _build_anthropic(
    settings: LLMSettings,
    env: Mapping[str, str],
    env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    from opencoat_runtime_llm import AnthropicLLMClient

    extras = _llm_extras(settings)
    model = extras.get("model") or env.get("ANTHROPIC_MODEL") or _DEFAULT_ANTHROPIC_MODEL
    api_key = extras.get("api_key") or env.get("ANTHROPIC_API_KEY")
    if not api_key:
        _require_explicit("anthropic", "api_key", "ANTHROPIC_API_KEY", env_explicit=env_explicit)
    base_url = extras.get("base_url") or env.get("ANTHROPIC_BASE_URL")
    return (
        AnthropicLLMClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=settings.timeout_seconds,
        ),
        LLMInfo(
            label=f"anthropic/{model}",
            kind="anthropic",
            real=True,
            requested=settings.provider,
        ),
    )


def _build_azure(
    settings: LLMSettings,
    env: Mapping[str, str],
    env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    from opencoat_runtime_llm import AzureOpenAILLMClient

    extras = _llm_extras(settings)
    deployment = (
        extras.get("deployment")
        or env.get("AZURE_OPENAI_DEPLOYMENT")
        or env.get("OPENCOAT_AZURE_DEPLOYMENT")
    )
    if not deployment:
        raise RuntimeError(
            "llm.provider=azure but no deployment configured. Set "
            "llm.deployment in the daemon config or AZURE_OPENAI_DEPLOYMENT "
            "in the environment."
        )

    endpoint = extras.get("endpoint") or env.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        _require_explicit("azure", "endpoint", "AZURE_OPENAI_ENDPOINT", env_explicit=env_explicit)
    api_key = extras.get("api_key") or env.get("AZURE_OPENAI_API_KEY")
    if not api_key:
        _require_explicit("azure", "api_key", "AZURE_OPENAI_API_KEY", env_explicit=env_explicit)

    # Honour ``OPENAI_API_VERSION`` in addition to the more specific
    # ``AZURE_OPENAI_API_VERSION`` (Codex P2 on PR-17): the Azure SDK
    # documents ``OPENAI_API_VERSION`` as its fallback, and we'd
    # otherwise pin ``_DEFAULT_AZURE_API_VERSION`` even when the
    # operator already set ``OPENAI_API_VERSION`` for the broader
    # OpenAI tooling.
    api_version = (
        extras.get("api_version")
        or env.get("AZURE_OPENAI_API_VERSION")
        or env.get("OPENAI_API_VERSION")
        or _DEFAULT_AZURE_API_VERSION
    )
    return (
        AzureOpenAILLMClient(
            deployment=deployment,
            api_version=api_version,
            endpoint=endpoint,
            api_key=api_key,
            timeout_seconds=settings.timeout_seconds,
        ),
        LLMInfo(
            label=f"azure/{deployment}",
            kind="azure",
            real=True,
            requested=settings.provider,
        ),
    )


# Ordered probe table for ``provider: auto``. We pick the *first*
# provider whose marker env var is set so operators with multiple
# credentials in their environment get a predictable choice — the
# precedence matches the install / docs order (OpenAI first, since
# that's the most common provider; then Anthropic; then Azure, which
# additionally requires a deployment name and is the most opinionated
# to mis-configure). The Azure entry intentionally requires *both*
# the API key and the deployment to be discoverable from env, since
# auto-detection without a deployment would just rediscover the same
# "no deployment configured" RuntimeError ``_build_azure`` raises.
def _auto_pick_provider(env: Mapping[str, str]) -> str | None:
    if env.get("BAI_API_KEY"):
        return "bai"
    if env.get("OPENAI_API_KEY"):
        return "openai"
    if env.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    azure_deployment = env.get("AZURE_OPENAI_DEPLOYMENT") or env.get("OPENCOAT_AZURE_DEPLOYMENT")
    if env.get("AZURE_OPENAI_API_KEY") and azure_deployment:
        return "azure"
    return None


def _build_auto(
    settings: LLMSettings,
    env: Mapping[str, str],
    env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    """``provider: auto`` — pick the first provider whose credentials are present.

    Falls back to a stub LLM (with a clearly distinct ``stub-fallback``
    label + a fix-it hint) when no credential set is found, so
    ``opencoat runtime up`` always succeeds with a zero-config install
    — the daemon and CLI loudly surface the degraded state instead of
    silently returning empty results.
    """
    picked = _auto_pick_provider(env)
    if picked is None:
        return (
            StubLLMClient(default_chat=_STUB_DEFAULT_CHAT),
            LLMInfo(
                label="stub-fallback",
                kind="stub",
                real=False,
                requested=settings.provider,
                hint=_STUB_FALLBACK_HINT,
            ),
        )
    builder = _LLM_PROVIDER_BUILDERS[picked]
    client, info = builder(settings, env, env_explicit)
    # Preserve the ``requested="auto"`` provenance so ``llm_info``
    # tells the operator *both* "we asked for auto" and "we got
    # openai" — invaluable when debugging "why did my Azure key get
    # picked over my OpenAI one".
    return client, LLMInfo(
        label=info.label,
        kind=info.kind,
        real=info.real,
        requested=settings.provider,
        hint=info.hint,
    )


# Builders for the explicit-named providers — referenced by both
# ``_build_llm`` (the public dispatcher) and ``_build_auto`` (which
# picks one of them).
_LLM_PROVIDER_BUILDERS: dict[str, _LlmBuilder] = {
    "bai": _build_bai,
    "openai": _build_openai,
    "anthropic": _build_anthropic,
    "azure": _build_azure,
}


_LLM_BUILDERS: dict[str, _LlmBuilder] = {
    "auto": _build_auto,
    "stub": _build_stub,
    **_LLM_PROVIDER_BUILDERS,
}


def _build_llm(
    settings: LLMSettings,
    env: Mapping[str, str],
    *,
    env_explicit: bool,
) -> tuple[LLMClient, LLMInfo]:
    name = settings.provider.lower()
    builder = _LLM_BUILDERS.get(name)
    if builder is None:
        raise ValueError(
            f"Unknown llm.provider={settings.provider!r}; expected one of: {sorted(_LLM_BUILDERS)}"
        )
    return builder(settings, env, env_explicit)


__all__ = ["BuiltRuntime", "LLMInfo", "build_runtime", "warm_persistent_stores"]
