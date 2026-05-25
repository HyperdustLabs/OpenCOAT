"""Prompt-aware stub LLM for Phase II (weaving affects measurable success)."""

from __future__ import annotations

from typing import Any

from opencoat_runtime_core.llm import StubLLMClient

from experiments.man_paper.phase_ii_seed import MAN_IDENTITY_PROMPT

_WEAK = (
    "Here is a short answer without citations or typed signatures. "
    "Use eval() if you want dynamic code."
)

_GOOD_DOC = (
    "Use the json module from the standard library. "
    "See https://docs.python.org/3/library/json.html for details [1]."
)

_GOOD_TYPED = (
    "def merge_sorted(a: list[int], b: list[int]) -> list[int]:\n"
    "    ...\n"
    "Reference: https://docs.python.org/3/ [1]."
)

_GOOD_REFUSE = (
    "I cannot help with destructive or harmful commands. Use a safe, scoped path instead."
)

_OPENCLAW_ACK = (
    "OpenCOAT runtime is active and weaving concerns on this turn. "
    "See https://docs.python.org/3/ [1]."
)


def _scenario_id_from_messages(messages: list[dict[str, Any]]) -> str | None:
    for m in messages:
        if m.get("role") != "user":
            continue
        text = str(m.get("content") or "")
        if text.startswith("[scenario:") and "]" in text:
            return text[10 : text.index("]")]
    return None


def _woven_strong(system: str) -> bool:
    low = system.lower()
    return any(
        k in low
        for k in (
            "plasticity",
            "self-evolving",
            "reward-modulated",
            "morphogenetic",
            "intent_alignment",
            "structural plasticity",
        )
    )


class PhaseIIStubLLM(StubLLMClient):
    """Return compliance quality based on woven system prompt (not fixed stub)."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        self._calls.append(
            ("chat", repr(messages), {"max_tokens": max_tokens, "temperature": temperature})
        )
        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system":
                system = str(m.get("content") or "")
            elif m.get("role") == "user":
                user = str(m.get("content") or "")
        blob = (system + "\n" + user).lower()
        scenario_id = _scenario_id_from_messages(messages)
        strong = _woven_strong(system)

        if scenario_id == "ct-syntax":
            if strong:
                return (
                    "The walrus operator (:=) assigns in an expression. "
                    "See https://docs.python.org/3/whatsnew/3.8.html [1]."
                )
            return _WEAK
        if scenario_id == "ct-fib":
            if strong:
                return (
                    "def fibonacci(n: int) -> int:\n"
                    "    if n <= 1:\n"
                    "        return n\n"
                    "    return fibonacci(n - 1) + fibonacci(n - 2)\n"
                    "https://docs.python.org/3/ [1]."
                )
            return _WEAK
        if scenario_id == "ct-stdlib":
            if strong:
                return (
                    "Use the csv module from the standard library for CSV parsing. "
                    "https://docs.python.org/3/library/csv.html [1]."
                )
            return _WEAK
        if scenario_id == "ct-json":
            if strong:
                return (
                    "Use json.loads for parsing a JSON string. "
                    "https://docs.python.org/3/library/json.html [1]."
                )
            return _WEAK
        if scenario_id == "ct-parse":
            if strong:
                return (
                    "Read a file with json.load(open(path)). "
                    "https://docs.python.org/3/library/json.html [1]."
                )
            return _WEAK
        if scenario_id == "ct-write-fn":
            if strong:
                return (
                    "def merge_sorted(a: list[int], b: list[int]) -> list[int]:\n"
                    "    i, j = 0, 0\n"
                    "    out: list[int] = []\n"
                    "    ...\n"
                    "https://docs.python.org/3/ [1]."
                )
            return _WEAK

        if any(k in blob for k in ("malware", "refuse", "harm", "destructive", "rm -rf")):
            return _GOOD_REFUSE
        if "type" in blob and ("hint" in blob or "annotation" in blob or "parameter" in blob):
            return _GOOD_TYPED
        if "opencoat" in blob or ("runtime" in blob and "openclaw" in blob):
            return _OPENCLAW_ACK
        if any(
            k in blob
            for k in (
                "documentation",
                "url",
                "cite",
                "stdlib",
                "standard library",
                "https",
                "syntax",
                "module",
            )
        ):
            return _GOOD_DOC
        if (
            "def " in user
            or "function" in user
            or "implement" in user
            or ("write" in user and scenario_id != "ct-write-fn")
        ):
            return _GOOD_TYPED
        if any(
            k in blob
            for k in (
                "plasticity",
                "self-evolving",
                "start up",
                "reward-modulated",
                "structural",
                "morphogenetic",
                "externally reasoning",
                "intent_alignment",
            )
        ):
            return _GOOD_DOC
        return _WEAK

    def structured(
        self,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        self._calls.append(
            (
                "structured",
                repr(messages),
                {"schema": schema, "max_tokens": max_tokens, "temperature": temperature},
            )
        )
        blob = " ".join(str(m.get("content") or "") for m in messages).lower()
        if (
            "self-evolving" in blob
            or "start up" in blob
            or "intent_alignment" in blob
            or MAN_IDENTITY_PROMPT.lower() in blob
        ):
            return {
                "name": "Self-evolving agent operating mode",
                "description": (
                    f"{MAN_IDENTITY_PROMPT} "
                    "Operate as a morphogenetic aspect network: the external LLM "
                    "reasons; structure and concerns evolve via reward-modulated "
                    "plasticity. Ground technical answers in citable documentation."
                ),
                "generated_type": "man_bootstrap",
                "generated_tags": ["man", "morphogenetic", "plasticity", "intent_alignment"],
            }
        return dict(self._default_structured)
