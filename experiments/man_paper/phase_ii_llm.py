"""Phase II LLM: B.AI / OpenAI / Anthropic / Azure / stub (aligned with daemon auto order)."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opencoat_runtime_core.ports import LLMClient

from experiments.man_paper.phase_ii_stub import PhaseIIStubLLM

_CODING_DIR = Path(__file__).resolve().parents[2] / "examples" / "02_coding_agent_demo"
_CODING_LLM: Any | None = None


def _coding_llm_module() -> Any:
    global _CODING_LLM
    if _CODING_LLM is not None:
        return _CODING_LLM
    pkg = "_phase_ii_coding_llm"
    spec = importlib.util.spec_from_file_location(pkg, _CODING_DIR / "llm.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg] = mod
    spec.loader.exec_module(mod)
    _CODING_LLM = mod
    return mod


def _force_stub() -> bool:
    return os.environ.get("OPENCOAT_PHASE_II_FORCE_STUB", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _auto_detect_provider(env: Mapping[str, str]) -> str:
    """Same precedence as ``runtime_builder._auto_pick_provider``."""
    if env.get("BAI_API_KEY"):
        return "bai"
    if env.get("OPENAI_API_KEY"):
        return "openai"
    if env.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if env.get("AZURE_OPENAI_ENDPOINT") and (
        env.get("OPENCOAT_DEMO_AZURE_DEPLOYMENT") or env.get("AZURE_OPENAI_DEPLOYMENT")
    ):
        return "azure"
    return "stub"


def _build_bai(env: Mapping[str, str]) -> tuple[LLMClient, str]:
    from opencoat_runtime_llm import BAI_DEFAULT_BASE_URL, BAI_DEFAULT_MODEL, BaiLLMClient

    model = env.get("BAI_MODEL", BAI_DEFAULT_MODEL)
    api_key = env.get("BAI_API_KEY")
    base_url = env.get("BAI_BASE_URL") or BAI_DEFAULT_BASE_URL
    timeout = float(
        env.get("OPENCOAT_PHASE_II_LLM_TIMEOUT_SECONDS") or env.get("BAI_TIMEOUT_SECONDS") or 20.0
    )
    return (
        BaiLLMClient(model=model, api_key=api_key, base_url=base_url, timeout_seconds=timeout),
        f"bai/{model}",
    )


def resolve_phase_ii_llm(
    provider: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> tuple[LLMClient, str, bool]:
    """Return ``(client, label, is_stub)``.

    Parameters
    ----------
    provider:
        ``bai``, ``openai``, ``anthropic``, ``azure``, ``stub``, or ``None``/``auto``
        (env probe: BAI → OpenAI → Anthropic → Azure → stub).

    Environment
    -----------
    ``BAI_API_KEY``, ``BAI_MODEL``, ``BAI_BASE_URL`` — see ``docs/config/bai-llm.md``.
    ``OPENCOAT_PHASE_II_FORCE_STUB=1`` — CI prompt-aware stub.
    """
    if _force_stub():
        return PhaseIIStubLLM(), "phase-ii-stub(forced)", True

    mapping: Mapping[str, str] = env if env is not None else os.environ
    chosen = (provider or os.environ.get("OPENCOAT_PHASE_II_PROVIDER") or "").strip().lower()
    if not chosen or chosen == "auto":
        chosen = _auto_detect_provider(mapping)

    if chosen == "bai":
        return (*_build_bai(mapping), False)
    if chosen == "stub":
        return PhaseIIStubLLM(), "phase-ii-stub", True

    llm_mod = _coding_llm_module()
    client, label = llm_mod.select_llm(chosen, env=mapping)
    if label == "stub" or chosen == "stub":
        return PhaseIIStubLLM(), label, True
    return client, label, False
