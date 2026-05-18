"""``opencoat configure llm`` — guided daemon LLM credential setup.

Writes a small ``~/.opencoat/daemon.yaml`` fragment (``llm.*`` only) and,
by default, a ``~/.opencoat/opencoat.env`` file with provider API keys so
``provider: auto`` can resolve without pasting secrets into YAML.

``python -m opencoat_runtime_daemon`` (and thus ``opencoat runtime up``)
calls :func:`~opencoat_runtime_daemon.config.loader.merge_user_llm_env_file`
before loading config so keys from ``opencoat.env`` are merged into the
daemon process (via ``os.environ.setdefault``), limited to an LLM-related
allow-list so arbitrary keys cannot reconfigure the runtime. Shell exports
still win when set. Operators who prefer not to use the file can delete it
and rely on ``export`` / systemd ``EnvironmentFile`` only.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

import yaml
from opencoat_runtime_llm.bai_client import BAI_DEFAULT_BASE_URL, BAI_DEFAULT_MODEL
from opencoat_runtime_llm.openai_client import OpenAILLMClient

Mode = Literal["env-file", "inline"]

_DEFAULT_YAML_REL = Path(".opencoat") / "daemon.yaml"
_DEFAULT_ENV_REL = Path(".opencoat") / "opencoat.env"

_DEFAULT_OPENAI_MODEL = OpenAILLMClient.DEFAULT_MODEL
_OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
_OPENAI_MODEL_PAGE_SIZE = 20

# Substrings that mark non-chat-completion model ids from GET /v1/models.
_OPENAI_MODEL_EXCLUDE_FRAGMENTS: tuple[str, ...] = (
    "embed",
    "whisper",
    "tts",
    "dall-e",
    "davinci",
    "babbage",
    "realtime",
    "transcribe",
    "moderation",
    "search",
    "audio",
    "image",
    "computer",
)

_OPENAI_MODEL_PREFERRED_ORDER: tuple[str, ...] = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "o4-mini",
    "o3-mini",
)


def _default_yaml_path() -> Path:
    return Path.home() / _DEFAULT_YAML_REL


def _default_env_path() -> Path:
    return Path.home() / _DEFAULT_ENV_REL


def _chmod_secret(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _env_key(name: str, env_path: Path, yaml_path: Path) -> str | None:
    """Resolve a credential from env file, process env, or inline ``llm.api_key``."""
    from_file = _parse_env_file(env_path).get(name)
    if from_file:
        return from_file
    from_os = os.environ.get(name)
    if from_os:
        return from_os
    llm = _load_yaml_dict(yaml_path).get("llm")
    if not isinstance(llm, dict):
        return None
    inline = llm.get("api_key")
    if not isinstance(inline, str) or not inline.strip():
        return None
    provider = llm.get("provider")
    if name == "BAI_API_KEY" and provider in ("bai", "auto"):
        return inline.strip()
    if name == "OPENAI_API_KEY" and provider in ("openai", "auto"):
        return inline.strip()
    if name == "ANTHROPIC_API_KEY" and provider in ("anthropic", "auto"):
        return inline.strip()
    if name == "AZURE_OPENAI_API_KEY" and provider in ("azure", "auto"):
        return inline.strip()
    return None


def _credential_source_label(name: str, env_path: Path, yaml_path: Path) -> str:
    if _parse_env_file(env_path).get(name):
        return str(env_path)
    if os.environ.get(name):
        return "environment"
    llm = _load_yaml_dict(yaml_path).get("llm")
    if isinstance(llm, dict) and isinstance(llm.get("api_key"), str) and llm.get("api_key"):
        return str(yaml_path)
    return "saved config"


def _azure_credential_parts(
    env_path: Path,
    yaml_path: Path,
    updates: dict[str, str] | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve Azure OpenAI key, endpoint, and deployment from disk or env."""
    merged = updates or {}
    env_file = _parse_env_file(env_path)
    llm = _load_yaml_dict(yaml_path).get("llm")
    llm_dict = llm if isinstance(llm, dict) else {}

    def _pick(name: str, yaml_field: str | None = None) -> str | None:
        val = merged.get(name) or env_file.get(name) or os.environ.get(name)
        if not val and yaml_field and isinstance(llm_dict.get(yaml_field), str):
            val = llm_dict[yaml_field]
        if not val and name == "AZURE_OPENAI_API_KEY":
            val = _env_key(name, env_path, yaml_path)
        return val.strip() if isinstance(val, str) and val.strip() else None

    return (
        _pick("AZURE_OPENAI_API_KEY"),
        _pick("AZURE_OPENAI_ENDPOINT", "endpoint"),
        _pick("AZURE_OPENAI_DEPLOYMENT", "deployment"),
    )


def _existing_bai_model(env_path: Path, yaml_path: Path) -> str | None:
    from_env = _parse_env_file(env_path).get("BAI_MODEL")
    if from_env:
        return from_env
    from_os = os.environ.get("BAI_MODEL")
    if from_os:
        return from_os.strip()
    llm = _load_yaml_dict(yaml_path).get("llm")
    if isinstance(llm, dict) and llm.get("provider") == "bai":
        model = llm.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None


def _existing_openai_model(env_path: Path, yaml_path: Path) -> str | None:
    llm = _load_yaml_dict(yaml_path).get("llm")
    if isinstance(llm, dict):
        prov = llm.get("provider")
        if prov in (None, "openai", "auto"):
            model = llm.get("model")
            if isinstance(model, str) and model.strip():
                return model.strip()
    from_env = _parse_env_file(env_path).get("OPENAI_MODEL")
    if from_env:
        return from_env
    from_os = os.environ.get("OPENAI_MODEL")
    return from_os.strip() if from_os else None


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if key and key not in out:
            out[key] = v.strip().strip('"').strip("'")
    return out


def _write_env_file(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _parse_env_file(path)
    merged.update({k: v for k, v in updates.items() if v})
    lines = [
        "# OpenCOAT daemon LLM credentials — chmod 600; do not commit.",
        "# The daemon merges allow-listed LLM keys on startup (setdefault); optional for shells:",
        "#   set -a && source ~/.opencoat/opencoat.env && set +a",
        "",
    ]
    for key in sorted(merged):
        val = merged[key]
        if not val:
            continue
        # Single-line values only; escape embedded newlines defensively.
        safe = val.replace("\n", "\\n").replace("\r", "")
        lines.append(f"{key}={safe}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    _chmod_secret(path)


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


# Slots ``--mode inline`` writes secrets into. Treated as
# "owned" by each ``_write_yaml_llm`` call: if the new payload
# doesn't include them, they're dropped — otherwise switching from
# ``inline`` back to ``env-file`` would silently leave the old
# ``llm.api_key`` (and friends) sitting on disk despite the wizard
# advertising env-file as "YAML has no secrets" (Codex P1 on PR-51).
_INLINE_SECRET_KEYS: tuple[str, ...] = ("api_key", "endpoint", "deployment")


def _write_yaml_llm(
    path: Path,
    *,
    llm: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _load_yaml_dict(path)
    old_llm = merged.get("llm")
    old_llm_dict = old_llm if isinstance(old_llm, dict) else {}
    cleaned_old = {k: v for k, v in old_llm_dict.items() if k not in _INLINE_SECRET_KEYS}
    merged["llm"] = {**cleaned_old, **llm}
    text = yaml.safe_dump(merged, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    if any(k in llm for k in _INLINE_SECRET_KEYS):
        _chmod_secret(path)


def _is_openai_chat_model_id(model_id: str) -> bool:
    """Heuristic filter for ids usable with chat.completions."""
    mid = model_id.strip()
    if not mid:
        return False
    lower = mid.lower()
    if any(frag in lower for frag in _OPENAI_MODEL_EXCLUDE_FRAGMENTS):
        return False
    return lower.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4"))


def _sort_openai_model_ids(ids: list[str], *, default: str) -> list[str]:
    """Stable order: default + common picks first, then alphabetical."""
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in (default, *_OPENAI_MODEL_PREFERRED_ORDER, *sorted(ids)):
        if candidate in ids and candidate not in seen:
            ordered.append(candidate)
            seen.add(candidate)
    return ordered


def fetch_openai_model_ids(
    api_key: str,
    *,
    base_url: str | None = None,
    timeout_seconds: float = 15.0,
) -> list[str]:
    """Return chat-oriented model ids from the OpenAI (or compatible) Models API."""
    root = (base_url or _OPENAI_MODELS_URL.rsplit("/models", 1)[0]).rstrip("/")
    url = f"{root}/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("models response is not a JSON object")
    raw = payload.get("data")
    if not isinstance(raw, list):
        raise ValueError("models response missing data[]")
    ids: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            mid = item.get("id")
            if isinstance(mid, str) and mid:
                ids.append(mid)
    filtered = [m for m in ids if _is_openai_chat_model_id(m)]
    return _sort_openai_model_ids(filtered, default=_DEFAULT_OPENAI_MODEL)


def _choose_openai_model_from_list(models: list[str], *, default: str) -> str:
    """Paginated menu over a pre-fetched model id list."""
    page_size = _OPENAI_MODEL_PAGE_SIZE
    total_pages = max(1, (len(models) + page_size - 1) // page_size)
    page = 0

    while True:
        start = page * page_size
        chunk = models[start : start + page_size]
        page_no = page + 1
        header = (
            f"\nOpenAI models (page {page_no}/{total_pages}; "
            "from your API key; chat-capable, filtered):"
        )
        print(header, file=sys.stderr)
        for i, mid in enumerate(chunk, start=1):
            global_idx = start + i
            hint = ""
            if mid == default and global_idx == 1:
                hint = " (recommended default)"
            elif mid == default:
                hint = " (current default)"
            print(f"  [{i}] {mid}{hint}", file=sys.stderr)
        print("  [0] Enter a custom model id", file=sys.stderr)
        if page < total_pages - 1:
            print("  [n] Next page", file=sys.stderr)
        if page > 0:
            print("  [p] Previous page", file=sys.stderr)

        if total_pages == 1:
            prompt = f"Model choice (1-{len(chunk)}, 0=custom) [1]: "
        else:
            nav = []
            if page < total_pages - 1:
                nav.append("n=next")
            if page > 0:
                nav.append("p=prev")
            nav_s = ", ".join(nav)
            prompt = f"Model choice (1-{len(chunk)}, 0=custom, {nav_s}): "
        choice = input(prompt).strip().lower()
        if not choice and page == 0 and total_pages == 1:
            choice = "1"
        if not choice and page == 0 and total_pages > 1:
            choice = "1"

        if choice in ("n", "next"):
            if page < total_pages - 1:
                page += 1
                continue
            print("configure llm: already on the last page", file=sys.stderr)
            continue
        if choice in ("p", "prev", "back"):
            if page > 0:
                page -= 1
                continue
            print("configure llm: already on the first page", file=sys.stderr)
            continue
        if choice == "0":
            custom = input(f"OpenAI model id [{default}]: ").strip()
            return custom or default
        try:
            idx = int(choice)
            if 1 <= idx <= len(chunk):
                selected = chunk[idx - 1]
                print(f"configure llm: selected model {selected}", file=sys.stderr)
                return selected
            print(
                f"configure llm: invalid choice {choice!r} "
                f"(this page has {len(chunk)} items); try again.",
                file=sys.stderr,
            )
            continue
        except ValueError:
            pass
        if choice:
            print(f"configure llm: selected model {choice}", file=sys.stderr)
            return choice
        if not choice:
            continue
        return default


def _prompt_openai_model(
    api_key: str,
    *,
    default: str = _DEFAULT_OPENAI_MODEL,
    base_url: str | None = None,
) -> str:
    """Interactive model picker backed by GET /v1/models, with manual fallback."""
    try:
        models = fetch_openai_model_ids(api_key, base_url=base_url)
    except (
        OSError,
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"configure llm: could not list OpenAI models ({exc}); enter a model id manually.",
            file=sys.stderr,
        )
        return input(f"OpenAI model [{default}]: ").strip() or default

    if not models:
        print(
            "configure llm: no chat-capable models returned — enter a model id manually.",
            file=sys.stderr,
        )
        return input(f"OpenAI model [{default}]: ").strip() or default

    return _choose_openai_model_from_list(models, default=default)


def _write_yaml_section(
    path: Path,
    *,
    storage: dict[str, Any] | None = None,
    ipc: dict[str, Any] | None = None,
) -> None:
    """Merge ``storage`` / ``ipc`` blocks into ``path`` without touching ``llm``.

    Used by ``opencoat configure daemon`` to flip the stores to sqlite
    (and pin the HTTP endpoint) while preserving whatever the LLM
    wizard previously wrote.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _load_yaml_dict(path)
    if storage is not None:
        existing = merged.get("storage")
        existing_dict = existing if isinstance(existing, dict) else {}
        merged["storage"] = {**existing_dict, **storage}
    if ipc is not None:
        existing = merged.get("ipc")
        existing_dict = existing if isinstance(existing, dict) else {}
        merged["ipc"] = {**existing_dict, **ipc}
    text = yaml.safe_dump(merged, default_flow_style=False, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")


def _collect_interactive(
    *,
    env_path: Path,
    yaml_path: Path,
) -> tuple[str, Mode, dict[str, str], dict[str, Any]]:
    print("OpenCOAT — configure daemon LLM\n", file=sys.stderr)
    print(
        "The runtime resolves credentials in this order when provider is `auto`:\n"
        "  BAI_API_KEY → OPENAI_API_KEY → ANTHROPIC_API_KEY → AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT\n",
        file=sys.stderr,
    )
    print(
        "Choose how secrets are stored:\n"
        "  [1] env-file (default) — keys in ~/.opencoat/opencoat.env; YAML has no secrets\n"
        "  [2] inline — keys embedded in daemon.yaml (chmod 600); convenient but risky if copied\n",
        file=sys.stderr,
    )
    mode_raw = input("Storage mode [1]: ").strip() or "1"
    mode: Mode = "inline" if mode_raw == "2" else "env-file"

    print(
        "\nProvider for daemon YAML:\n"
        "  [1] auto (recommended)\n"
        "  [2] b.ai (B.AI — https://api.b.ai)\n"
        "  [3] openai\n"
        "  [4] anthropic\n"
        "  [5] azure\n"
        "  [6] stub (no external LLM — hermetic / CI)\n",
        file=sys.stderr,
    )
    p_raw = input("Provider [1]: ").strip() or "1"
    provider_map = {
        "1": "auto",
        "2": "bai",
        "3": "openai",
        "4": "anthropic",
        "5": "azure",
        "6": "stub",
    }
    provider = provider_map.get(p_raw, "auto")

    if mode == "inline" and provider == "auto":
        print(
            "configure llm: inline mode cannot be used with provider=auto "
            "(which credential would be embedded?). Choose env-file or an explicit provider.",
            file=sys.stderr,
        )
        sys.exit(2)

    env_updates: dict[str, str] = {}
    llm_inline: dict[str, Any] = {"provider": provider, "timeout_seconds": 30.0}

    if provider == "stub":
        llm_inline["provider"] = "stub"
        return provider, mode, env_updates, llm_inline

    def gp(prompt: str) -> str:
        return getpass.getpass(prompt)

    if provider in ("auto", "bai"):
        existing_bai = _env_key("BAI_API_KEY", env_path, yaml_path)
        if existing_bai:
            src = _credential_source_label("BAI_API_KEY", env_path, yaml_path)
            bai_prompt = f"B.AI API key (Enter to keep existing from {src}): "
        else:
            bai_prompt = "B.AI API key (Enter to skip): "
        key = gp(bai_prompt).strip()
        effective_bai = key or existing_bai
        if key:
            env_updates["BAI_API_KEY"] = key
        if provider == "bai" and not effective_bai:
            print("configure llm: bai provider requires an API key", file=sys.stderr)
            sys.exit(2)
        default_model = _existing_bai_model(env_path, yaml_path) or BAI_DEFAULT_MODEL
        if effective_bai:
            if provider == "bai":
                model = _prompt_openai_model(
                    effective_bai,
                    default=default_model or BAI_DEFAULT_MODEL,
                    base_url=BAI_DEFAULT_BASE_URL,
                )
            else:
                model = input(f"B.AI model [{BAI_DEFAULT_MODEL}]: ").strip() or BAI_DEFAULT_MODEL
            if provider == "bai":
                llm_inline["model"] = model
            elif key or existing_bai:
                env_updates["BAI_MODEL"] = model

    if provider in ("auto", "openai"):
        existing_openai = _env_key("OPENAI_API_KEY", env_path, yaml_path)
        if existing_openai:
            src = _credential_source_label("OPENAI_API_KEY", env_path, yaml_path)
            openai_prompt = f"OpenAI API key (Enter to keep existing from {src}): "
        else:
            openai_prompt = "OpenAI API key (Enter to skip): "
        key = gp(openai_prompt).strip()
        effective_openai = key or existing_openai
        if key:
            env_updates["OPENAI_API_KEY"] = key
        if provider == "openai" and not effective_openai:
            print("configure llm: openai provider requires an API key", file=sys.stderr)
            sys.exit(2)
        default_model = _existing_openai_model(env_path, yaml_path) or _DEFAULT_OPENAI_MODEL
        if effective_openai:
            model = _prompt_openai_model(effective_openai, default=default_model)
        else:
            model = input(f"OpenAI model [{default_model}]: ").strip() or default_model
        if provider == "openai":
            llm_inline["model"] = model
        elif key or existing_openai:
            env_updates["OPENAI_MODEL"] = model

    if provider in ("auto", "anthropic"):
        existing_anthropic = _env_key("ANTHROPIC_API_KEY", env_path, yaml_path)
        if existing_anthropic:
            src = _credential_source_label("ANTHROPIC_API_KEY", env_path, yaml_path)
            anthropic_prompt = f"Anthropic API key (Enter to keep existing from {src}): "
        else:
            anthropic_prompt = "Anthropic API key (Enter to skip): "
        key = gp(anthropic_prompt).strip()
        effective_anthropic = key or existing_anthropic
        if key:
            env_updates["ANTHROPIC_API_KEY"] = key
        if provider == "anthropic" and not effective_anthropic:
            print("configure llm: anthropic provider requires an API key", file=sys.stderr)
            sys.exit(2)
        if provider == "anthropic":
            model = (
                input("Anthropic model [claude-3-5-haiku-latest]: ").strip()
                or "claude-3-5-haiku-latest"
            )
            llm_inline["model"] = model
        elif key:
            m = input("ANTHROPIC_MODEL override (Enter to skip): ").strip()
            if m:
                env_updates["ANTHROPIC_MODEL"] = m

    if provider in ("auto", "azure"):
        az_key_existing, az_ep_existing, az_dep_existing = _azure_credential_parts(
            env_path, yaml_path
        )
        if az_key_existing:
            az_src = _credential_source_label("AZURE_OPENAI_API_KEY", env_path, yaml_path)
            az_key_prompt = f"Azure OpenAI API key (Enter to keep existing from {az_src}): "
        else:
            az_key_prompt = "Azure OpenAI API key (Enter to skip): "
        key = gp(az_key_prompt).strip() or (az_key_existing or "")
        if az_ep_existing:
            endpoint = (
                input(f"Azure endpoint URL (Enter to keep [{az_ep_existing}]): ").strip()
                or az_ep_existing
            )
        else:
            endpoint = input("Azure endpoint URL (Enter to skip): ").strip()
        if az_dep_existing:
            deployment = (
                input(f"Azure deployment name (Enter to keep [{az_dep_existing}]): ").strip()
                or az_dep_existing
            )
        else:
            deployment = input("Azure deployment name (Enter to skip): ").strip()
        az_key, az_ep, az_dep = _azure_credential_parts(
            env_path,
            yaml_path,
            {
                **env_updates,
                **(
                    {
                        "AZURE_OPENAI_API_KEY": key,
                        "AZURE_OPENAI_ENDPOINT": endpoint,
                        "AZURE_OPENAI_DEPLOYMENT": deployment,
                    }
                    if key or endpoint or deployment
                    else {}
                ),
            },
        )
        if provider == "azure":
            if not (az_key and az_ep and az_dep):
                print(
                    "configure llm: azure provider requires API key, endpoint, and deployment",
                    file=sys.stderr,
                )
                sys.exit(2)
            if key:
                env_updates["AZURE_OPENAI_API_KEY"] = key
            if endpoint:
                env_updates["AZURE_OPENAI_ENDPOINT"] = endpoint
            if deployment:
                env_updates["AZURE_OPENAI_DEPLOYMENT"] = deployment
        elif key or endpoint or deployment:
            if not (az_key and az_ep and az_dep):
                print(
                    "configure llm: for auto + Azure, provide all three: "
                    "API key, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT",
                    file=sys.stderr,
                )
                sys.exit(2)
            if key:
                env_updates["AZURE_OPENAI_API_KEY"] = key
            if endpoint:
                env_updates["AZURE_OPENAI_ENDPOINT"] = endpoint
            if deployment:
                env_updates["AZURE_OPENAI_DEPLOYMENT"] = deployment

    has_bai = bool("BAI_API_KEY" in env_updates or _env_key("BAI_API_KEY", env_path, yaml_path))
    has_openai = bool(
        "OPENAI_API_KEY" in env_updates or _env_key("OPENAI_API_KEY", env_path, yaml_path)
    )
    has_anthropic = bool(
        "ANTHROPIC_API_KEY" in env_updates or _env_key("ANTHROPIC_API_KEY", env_path, yaml_path)
    )
    az_key, az_ep, az_dep = _azure_credential_parts(env_path, yaml_path, env_updates)
    has_azure = bool(az_key and az_ep and az_dep)

    if provider == "auto" and not (has_bai or has_openai or has_anthropic or has_azure):
        print(
            "configure llm: provider=auto needs at least one of: "
            "BAI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or Azure triple",
            file=sys.stderr,
        )
        sys.exit(2)

    if mode == "inline" and provider != "stub":
        # Move secrets from env_updates into llm_inline for yaml
        if "BAI_API_KEY" in env_updates:
            llm_inline["api_key"] = env_updates.pop("BAI_API_KEY")
        if "OPENAI_API_KEY" in env_updates:
            llm_inline["api_key"] = env_updates.pop("OPENAI_API_KEY")
        if "ANTHROPIC_API_KEY" in env_updates:
            llm_inline["api_key"] = env_updates.pop("ANTHROPIC_API_KEY")
        if "AZURE_OPENAI_API_KEY" in env_updates:
            llm_inline["api_key"] = env_updates.pop("AZURE_OPENAI_API_KEY")
        if "AZURE_OPENAI_ENDPOINT" in env_updates:
            llm_inline["endpoint"] = env_updates.pop("AZURE_OPENAI_ENDPOINT")
        if "AZURE_OPENAI_DEPLOYMENT" in env_updates:
            llm_inline["deployment"] = env_updates.pop("AZURE_OPENAI_DEPLOYMENT")
        if env_updates:
            print(
                f"configure llm: inline mode cannot represent extra env keys {sorted(env_updates)} — "
                "dropping them (use env-file mode instead).",
                file=sys.stderr,
            )

    return provider, mode, env_updates, llm_inline


def _collect_non_interactive(
    args: argparse.Namespace,
) -> tuple[str, Mode, dict[str, str], dict[str, Any]]:
    provider = args.provider
    mode: Mode = "inline" if args.mode == "inline" else "env-file"
    env_updates: dict[str, str] = {}
    llm: dict[str, Any] = {"provider": provider, "timeout_seconds": float(args.timeout_seconds)}

    if provider == "stub":
        return provider, mode, env_updates, llm

    if args.model:
        llm["model"] = args.model
    if provider == "bai" and args.bai_base_url:
        llm["base_url"] = args.bai_base_url
    if provider == "openai" and args.openai_base_url:
        llm["base_url"] = args.openai_base_url
    if provider == "anthropic" and args.anthropic_base_url:
        llm["base_url"] = args.anthropic_base_url

    if args.bai_api_key:
        env_updates["BAI_API_KEY"] = args.bai_api_key
    if args.bai_model_env:
        env_updates["BAI_MODEL"] = args.bai_model_env
    if args.openai_api_key:
        env_updates["OPENAI_API_KEY"] = args.openai_api_key
    if args.openai_model_env:
        env_updates["OPENAI_MODEL"] = args.openai_model_env
    if args.anthropic_api_key:
        env_updates["ANTHROPIC_API_KEY"] = args.anthropic_api_key
    if args.anthropic_model_env:
        env_updates["ANTHROPIC_MODEL"] = args.anthropic_model_env
    if args.azure_api_key:
        env_updates["AZURE_OPENAI_API_KEY"] = args.azure_api_key
    if args.azure_endpoint:
        env_updates["AZURE_OPENAI_ENDPOINT"] = args.azure_endpoint
    if args.azure_deployment:
        env_updates["AZURE_OPENAI_DEPLOYMENT"] = args.azure_deployment

    env_path = args.env.expanduser()
    yaml_path = args.yaml.expanduser()
    bai_key = args.bai_api_key or _env_key("BAI_API_KEY", env_path, yaml_path)
    openai_key = args.openai_api_key or _env_key("OPENAI_API_KEY", env_path, yaml_path)
    anthropic_key = args.anthropic_api_key or _env_key("ANTHROPIC_API_KEY", env_path, yaml_path)

    if provider == "bai" and not bai_key:
        print(
            "configure llm: --provider bai requires --bai-api-key "
            "(or an existing key in opencoat.env / daemon.yaml)",
            file=sys.stderr,
        )
        sys.exit(2)
    if provider == "openai" and not openai_key:
        print(
            "configure llm: --provider openai requires --openai-api-key "
            "(or an existing key in opencoat.env / daemon.yaml)",
            file=sys.stderr,
        )
        sys.exit(2)
    if provider == "anthropic" and not anthropic_key:
        print(
            "configure llm: --provider anthropic requires --anthropic-api-key "
            "(or an existing key in opencoat.env / daemon.yaml)",
            file=sys.stderr,
        )
        sys.exit(2)
    if provider == "azure" and not (
        args.azure_api_key and args.azure_endpoint and args.azure_deployment
    ):
        print(
            "configure llm: --provider azure requires --azure-api-key, --azure-endpoint, "
            "--azure-deployment",
            file=sys.stderr,
        )
        sys.exit(2)
    if provider == "auto":
        has_bai = bool(bai_key)
        has_openai = bool(openai_key)
        has_anthropic = bool(anthropic_key)
        az_key, az_ep, az_dep = _azure_credential_parts(
            env_path,
            yaml_path,
            {
                k: v
                for k, v in (
                    ("AZURE_OPENAI_API_KEY", args.azure_api_key),
                    ("AZURE_OPENAI_ENDPOINT", args.azure_endpoint),
                    ("AZURE_OPENAI_DEPLOYMENT", args.azure_deployment),
                )
                if v
            },
        )
        has_azure = bool(az_key and az_ep and az_dep)
        if not (has_bai or has_openai or has_anthropic or has_azure):
            print(
                "configure llm: --provider auto needs at least one credential set "
                "(bai, openai, anthropic, or full azure triple)",
                file=sys.stderr,
            )
            sys.exit(2)

    if mode == "inline":
        if provider == "bai":
            llm["api_key"] = bai_key
        elif provider == "openai":
            llm["api_key"] = openai_key
        elif provider == "anthropic":
            llm["api_key"] = anthropic_key
        elif provider == "azure":
            az_key, az_ep, az_dep = _azure_credential_parts(
                env_path,
                yaml_path,
                {
                    k: v
                    for k, v in (
                        ("AZURE_OPENAI_API_KEY", args.azure_api_key),
                        ("AZURE_OPENAI_ENDPOINT", args.azure_endpoint),
                        ("AZURE_OPENAI_DEPLOYMENT", args.azure_deployment),
                    )
                    if v
                },
            )
            if not (az_key and az_ep and az_dep):
                print(
                    "configure llm: --provider azure requires --azure-api-key, --azure-endpoint, "
                    "--azure-deployment (or existing values in opencoat.env / daemon.yaml)",
                    file=sys.stderr,
                )
                sys.exit(2)
            llm["api_key"] = az_key
            llm["endpoint"] = az_ep
            llm["deployment"] = az_dep
        elif provider == "auto":
            print(
                "configure llm: --mode inline does not support --provider auto "
                "(ambiguous which key to embed). Use --mode env-file or pick an explicit provider.",
                file=sys.stderr,
            )
            sys.exit(2)
        env_updates.clear()

    return provider, mode, env_updates, llm


def _configure_llm(args: argparse.Namespace) -> int:
    yaml_path: Path = args.yaml.expanduser()
    env_path: Path = args.env.expanduser()

    if args.non_interactive:
        provider, _mode, env_updates, llm = _collect_non_interactive(args)
    else:
        if not sys.stdin.isatty():
            print(
                "configure llm: stdin is not a TTY — re-run with --non-interactive and the "
                "appropriate --openai-api-key / … flags, or attach a terminal.",
                file=sys.stderr,
            )
            return 2
        provider, _mode, env_updates, llm = _collect_interactive(
            env_path=env_path,
            yaml_path=yaml_path,
        )

    # Strip empty optional llm keys for cleaner yaml
    llm_out = {k: v for k, v in llm.items() if v not in ("", None)}

    _write_yaml_llm(yaml_path, llm=llm_out)
    print(f"configure llm: wrote {yaml_path}", file=sys.stderr)
    model_written = llm_out.get("model")
    if isinstance(model_written, str) and model_written:
        print(f"configure llm: llm.model = {model_written}", file=sys.stderr)

    wrote_any_env = False
    if env_updates:
        _write_env_file(env_path, env_updates)
        wrote_any_env = True
        print(f"configure llm: wrote {env_path}", file=sys.stderr)
    elif provider == "stub":
        print("configure llm: stub provider — no env file updates", file=sys.stderr)

    print("\n--- Next steps ---", file=sys.stderr)
    if wrote_any_env:
        print(
            f"  1. Start the daemon — it merges allow-listed LLM keys from {env_path} on startup "
            f"(no `source` required for the daemon process):\n"
            f"       opencoat runtime up --config {yaml_path} --pid-file ~/.opencoat/opencoat.pid\n"
            f"  2. Confirm the real provider:\n"
            f"       opencoat runtime status --config {yaml_path} --pid-file ~/.opencoat/opencoat.pid\n"
            f"  Optional: `set -a && source {env_path} && set +a` if you want the same exports in "
            f"your interactive shell for other tools.\n",
            file=sys.stderr,
        )
    else:
        print(
            f"  1. Start the daemon:\n"
            f"       opencoat runtime up --config {yaml_path} --pid-file ~/.opencoat/opencoat.pid\n"
            f"  2. Confirm LLM wiring:\n"
            f"       opencoat runtime status --config {yaml_path} --pid-file ~/.opencoat/opencoat.pid\n",
            file=sys.stderr,
        )
    print(
        "Full annotated sample: docs/config/daemon.yaml.example in the OpenCOAT repo.\n",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# configure daemon — persistent storage + HTTP endpoint
# ---------------------------------------------------------------------------


_DEFAULT_CONCERN_DB_REL = Path(".opencoat") / "concerns.sqlite"
_DEFAULT_DCN_DB_REL = Path(".opencoat") / "dcn.sqlite"
_DEFAULT_PID_REL = Path(".opencoat") / "opencoat.pid"


def _configure_daemon(args: argparse.Namespace) -> int:
    """Write / merge sqlite + HTTP settings into the user's daemon YAML.

    The bundled ``default.yaml`` already uses sqlite under ``~/.opencoat/``
    with HTTP on ``127.0.0.1:7878``. This wizard is for **custom** database
    paths or listener settings; it preserves any ``llm:`` block from
    ``opencoat configure llm``.
    """
    yaml_path: Path = args.yaml.expanduser()
    concern_db: Path = Path(args.concern_db).expanduser()
    dcn_db: Path = Path(args.dcn_db).expanduser()

    storage_block: dict[str, Any] = {
        "concern_store": {"kind": "sqlite", "path": str(concern_db)},
        "dcn_store": {"kind": "sqlite", "path": str(dcn_db)},
    }
    ipc_block: dict[str, Any] = {
        "http": {
            "enabled": True,
            "host": args.http_host,
            "port": int(args.http_port),
            "path": args.http_path,
        },
    }

    _write_yaml_section(yaml_path, storage=storage_block, ipc=ipc_block)
    # Make sure the parent dir for the sqlite files exists eagerly so a
    # follow-up ``opencoat runtime up`` doesn't have to. The stores
    # themselves also ``mkdir -p`` on first construction; doing it here
    # too keeps the wizard's output ("wrote …") honest.
    for db_path in (concern_db, dcn_db):
        with contextlib.suppress(OSError):
            db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"configure daemon: wrote {yaml_path}", file=sys.stderr)
    print(
        "  storage.concern_store -> sqlite "
        f"({concern_db})\n  storage.dcn_store     -> sqlite ({dcn_db})\n"
        f"  ipc.http              -> http://{args.http_host}:{args.http_port}{args.http_path}",
        file=sys.stderr,
    )

    pid_path = Path(args.pid_file).expanduser() if args.pid_file else None
    pid_arg = f" --pid-file {pid_path}" if pid_path else ""

    print("\n--- Next steps ---", file=sys.stderr)
    print(
        "  1. (If you haven't yet) configure your LLM credentials:\n"
        f"       opencoat configure llm --yaml {yaml_path}\n"
        "  2. Start the daemon — `runtime up` double-forks by default, so the\n"
        "     daemon stays alive after the terminal closes. Just don't run\n"
        "     `runtime down` and it'll keep serving across host-agent sessions:\n"
        f"       opencoat runtime up --config {yaml_path}{pid_arg}\n"
        "  3. (Optional) install OS autostart so the daemon survives reboots:\n"
        "       opencoat service install\n"
        "  4. Confirm:\n"
        f"       opencoat runtime status --config {yaml_path}{pid_arg}\n"
        "\n"
        "  The bundled default already uses sqlite under ~/.opencoat/; this\n"
        "  wizard updates paths and the HTTP bind if you need non-defaults.\n",
        file=sys.stderr,
    )
    return 0


def _register_daemon(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "daemon",
        help=(
            "configure persistent storage + HTTP endpoint for the long-running "
            "daemon (writes ~/.opencoat/daemon.yaml)"
        ),
    )
    p.add_argument(
        "--yaml",
        dest="yaml",
        type=Path,
        default=_default_yaml_path(),
        help=f"path to daemon YAML to create/update (default: ~/{_DEFAULT_YAML_REL})",
    )
    p.add_argument(
        "--concern-db",
        type=Path,
        default=Path.home() / _DEFAULT_CONCERN_DB_REL,
        help=f"path to ConcernStore sqlite file (default: ~/{_DEFAULT_CONCERN_DB_REL})",
    )
    p.add_argument(
        "--dcn-db",
        type=Path,
        default=Path.home() / _DEFAULT_DCN_DB_REL,
        help=f"path to DCNStore sqlite file (default: ~/{_DEFAULT_DCN_DB_REL})",
    )
    p.add_argument(
        "--http-host",
        default="127.0.0.1",
        help="ipc.http.host (default: 127.0.0.1 — local only)",
    )
    p.add_argument(
        "--http-port",
        type=int,
        default=7878,
        help="ipc.http.port (default: 7878)",
    )
    p.add_argument(
        "--http-path",
        default="/rpc",
        help="ipc.http.path (default: /rpc)",
    )
    p.add_argument(
        "--pid-file",
        type=Path,
        default=Path.home() / _DEFAULT_PID_REL,
        help=f"PID file path printed in the next-steps hint (default: ~/{_DEFAULT_PID_REL})",
    )
    p.set_defaults(func=_configure_daemon)


def _register_llm(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "llm",
        help="guided setup for daemon LLM credentials (writes ~/.opencoat/daemon.yaml + opencoat.env)",
    )
    p.add_argument(
        "--yaml",
        dest="yaml",
        type=Path,
        default=_default_yaml_path(),
        help=f"path to daemon YAML to create/update (default: ~/{_DEFAULT_YAML_REL})",
    )
    p.add_argument(
        "--env",
        dest="env",
        type=Path,
        default=_default_env_path(),
        help=f"path to env file for API keys (default: ~/{_DEFAULT_ENV_REL}; env-file mode only)",
    )
    p.add_argument(
        "--mode",
        choices=("env-file", "inline"),
        default="env-file",
        help="env-file: keys in opencoat.env (default); inline: secrets embedded in YAML (chmod 600)",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="read credentials from flags instead of prompts",
    )
    p.add_argument(
        "--provider",
        choices=("auto", "bai", "openai", "anthropic", "azure", "stub"),
        default="auto",
        help="daemon llm.provider (non-interactive default: auto)",
    )
    p.add_argument(
        "--timeout-seconds", type=float, default=30.0, help="llm.timeout_seconds written to YAML"
    )
    p.add_argument(
        "--model",
        default=None,
        help="llm.model in YAML (bai/openai/anthropic explicit providers)",
    )
    p.add_argument(
        "--bai-api-key", default=os.environ.get("BAI_API_KEY"), help="non-interactive B.AI key"
    )
    p.add_argument("--bai-model-env", default=None, help="set BAI_MODEL in env file (auto mode)")
    p.add_argument(
        "--bai-base-url",
        default=None,
        help="llm.base_url when provider=bai (default https://api.b.ai/v1)",
    )
    p.add_argument(
        "--openai-api-key", default=os.environ.get("OPENAI_API_KEY"), help="non-interactive"
    )
    p.add_argument(
        "--openai-model-env", default=None, help="set OPENAI_MODEL in env file (auto mode)"
    )
    p.add_argument(
        "--anthropic-api-key", default=os.environ.get("ANTHROPIC_API_KEY"), help="non-interactive"
    )
    p.add_argument("--anthropic-model-env", default=None, help="set ANTHROPIC_MODEL in env file")
    p.add_argument(
        "--azure-api-key", default=os.environ.get("AZURE_OPENAI_API_KEY"), help="non-interactive"
    )
    p.add_argument(
        "--azure-endpoint", default=os.environ.get("AZURE_OPENAI_ENDPOINT"), help="non-interactive"
    )
    p.add_argument("--azure-deployment", default=os.environ.get("AZURE_OPENAI_DEPLOYMENT"), help="")
    p.add_argument(
        "--openai-base-url", default=None, help="llm.base_url for OpenAI-compatible gateways"
    )
    p.add_argument(
        "--anthropic-base-url", default=None, help="llm.base_url when provider=anthropic"
    )
    p.set_defaults(func=_configure_llm)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "configure",
        help="interactive configuration helpers (LLM credentials, …)",
    )
    inner = p.add_subparsers(dest="configure_target", required=True)
    _register_llm(inner)
    _register_daemon(inner)


__all__ = ["register"]
