"""Apply :data:`AdviceType.TOOL_GUARD` advice to OpenClaw tool calls (M5 #30).

OpenClaw represents in-flight tool calls as mutable
``{"name": ..., "arguments": {...}}`` dicts sitting between the LLM
step and the actual tool dispatch. The runtime's :class:`ConcernWeaver`
emits :data:`AdviceType.TOOL_GUARD` advice with default
:attr:`target` = ``"tool_call.arguments.*"`` and
:attr:`mode` = :attr:`WeavingOperation.BLOCK` (see
``packages/opencoat-runtime-core/opencoat_runtime_core/weaving/_defaults.py``).

The raw :class:`OpenClawInjector` would dutifully overwrite every
existing argument with the policy text, which technically satisfies
the wire spec but leaves the host unable to tell whether the call
should:

1. be *refused* outright with a policy reason (whole-call BLOCK), or
2. be *executed* with mutated / redacted arguments (per-arg REPLACE),
   or
3. be *executed as-is* with policy notes attached for audit
   (append-style advice).

:class:`OpenClawToolGuard` is the small interpreter that sits above
the injector and decodes these intents into a structured
:class:`ToolGuardOutcome`. Hosts call it once per tool call:

.. code-block:: python

   outcome = adapter.guard_tool_call(tool_call, injection)
   if outcome.blocked:
       refuse(tool_call["name"], outcome.block_reason)
   else:
       dispatch(tool_call["name"], outcome.arguments, notes=outcome.notes)

Semantics (per :class:`Injection` row, scoped to ``tool_call.*`` rows
only — rows for ``runtime_prompt.*`` / ``response.*`` are left for the
broader :meth:`OpenClawAdapter.apply_injection` path):

* **BLOCK / SUPPRESS / ESCALATE** anywhere under ``tool_call.*`` →
  mark the outcome as blocked and accumulate ``content`` into
  ``block_reason`` (newline-joined when multiple blocks fire). The
  arguments dict is preserved as-is so audit logs can still see what
  *would* have been dispatched.
* **REPLACE / REWRITE / COMPRESS** — only acted on when the target
  resolves under ``tool_call.arguments`` (either ``tool_call.arguments``
  itself or a subpath). The remainder of the target is routed through
  :class:`OpenClawInjector` against the arguments dict so wildcard
  handling and path walking stay in one place. Overwrite rows pointed
  at other ``tool_call.*`` slots (e.g. ``tool_call.name``) are silently
  dropped — rewriting tool names is not a coherent dispatch state
  (Codex P1 on PR #30 — would otherwise corrupt
  :attr:`ToolGuardOutcome.arguments` into a string).
* **INSERT / ANNOTATE / WARN / VERIFY / DEFER** → append ``content``
  to :attr:`ToolGuardOutcome.notes`. Notes don't change dispatchable
  arguments; they let the host attach policy text to its audit /
  observability stream without polluting the call itself.

The input ``tool_call`` dict is never mutated — the outcome owns a
deep copy of the (possibly rewritten) arguments.
"""

from __future__ import annotations

import copy
from typing import Any

from opencoat_runtime_protocol import ConcernInjection, Injection
from pydantic import BaseModel, ConfigDict, Field

from .injector import _APPEND_MODES, _BLOCK_MODES, _OVERWRITE_MODES, OpenClawInjector

# Any target under this prefix is "this tool call's business". Everything
# else (runtime_prompt.*, response.*) is left for the broader injection
# path so guards stay focused on tool dispatch decisions.
_TOOL_CALL_PREFIX = "tool_call."

# Only overwrite rows under this prefix actually rewrite arguments —
# other tool_call.* slots (e.g. tool_call.name) aren't dispatchable
# argument paths, so silently drop overwrite rows aimed at them.
_ARGUMENTS_PREFIX = "tool_call.arguments"


def _targets_arguments(target: str) -> bool:
    """``True`` for ``tool_call.arguments`` and any subpath under it."""
    return target == _ARGUMENTS_PREFIX or target.startswith(f"{_ARGUMENTS_PREFIX}.")


class ToolGuardOutcome(BaseModel):
    """Structured result of applying TOOL_GUARD advice to one tool call.

    Hosts inspect this rather than the raw post-injection context so
    "refuse vs mutate vs annotate" stays a single decision point.
    """

    model_config = ConfigDict(extra="forbid")

    blocked: bool = False
    """``True`` once any block-mode row hit ``tool_call.*``."""

    block_reason: str | None = None
    """Newline-joined ``content`` from every block row that fired."""

    arguments: dict[str, Any] = Field(default_factory=dict)
    """Final argument map. Always a fresh dict — never aliases input."""

    notes: list[str] = Field(default_factory=list)
    """Append-mode policy text in the order it arrived."""


class OpenClawToolGuard:
    """Apply :data:`AdviceType.TOOL_GUARD` advice to a single tool call."""

    def __init__(self, injector: OpenClawInjector | None = None) -> None:
        # Share an injector with the broader adapter when wired through
        # :class:`OpenClawAdapter` so wildcard / config semantics stay
        # identical across the two surfaces.
        self._injector = injector or OpenClawInjector()

    def guard(
        self,
        tool_call: dict[str, Any],
        injection: ConcernInjection,
    ) -> ToolGuardOutcome:
        """Return the :class:`ToolGuardOutcome` for ``tool_call`` under ``injection``.

        ``tool_call`` is treated as immutable; the outcome's
        ``arguments`` field is a deep-copy the host can splice back at
        its discretion. Rows whose target does not start with
        ``"tool_call."`` are ignored on the assumption the host will
        dispatch them through :meth:`OpenClawAdapter.apply_injection`.
        """
        outcome = ToolGuardOutcome(arguments=copy.deepcopy(tool_call.get("arguments", {}) or {}))
        for row in injection.injections:
            if not row.target.startswith(_TOOL_CALL_PREFIX):
                continue
            self._dispatch(row, outcome)
        return outcome

    # ------------------------------------------------------------------
    # one row
    # ------------------------------------------------------------------

    def _dispatch(self, row: Injection, outcome: ToolGuardOutcome) -> None:
        mode = row.mode

        if mode in _BLOCK_MODES:
            outcome.blocked = True
            if outcome.block_reason:
                outcome.block_reason = f"{outcome.block_reason}\n{row.content}"
            else:
                outcome.block_reason = row.content
            return

        if mode in _OVERWRITE_MODES:
            # Codex P1 on PR #30 — only routes under tool_call.arguments
            # are legal overwrite targets. Dropping the row keeps the
            # ``ToolGuardOutcome.arguments`` dict contract intact when a
            # weaver emits ``tool_call.*`` or ``tool_call.name`` rows.
            if not _targets_arguments(row.target):
                return
            outcome.arguments = self._mutate_arguments(outcome.arguments, row)
            return

        if mode in _APPEND_MODES:
            outcome.notes.append(row.content)
            return

        # Unknown / future operation — keep as a note so the host can
        # decide what to do rather than silently dropping advice.
        outcome.notes.append(row.content)

    def _mutate_arguments(
        self,
        arguments: dict[str, Any],
        row: Injection,
    ) -> dict[str, Any]:
        """Route a single overwrite row through the underlying injector.

        Strips the ``tool_call.arguments[.]`` prefix from the row's
        target and applies the *remainder* against a copy of the
        arguments dict directly. That lets us reuse the injector's
        wildcard + path-walking logic verbatim without ever exposing
        sibling ``tool_call.*`` keys (e.g. ``name``) to overwrite, which
        would otherwise corrupt the ``ToolGuardOutcome.arguments``
        contract.

        A bare ``tool_call.arguments`` target (no leaf) is interpreted
        as ``*`` — "redact every existing argument" — so it gets the
        same trailing-wildcard semantics as ``tool_call.arguments.*``.
        """
        remainder = row.target[len(_ARGUMENTS_PREFIX) :].lstrip(".")
        if not remainder:
            remainder = "*"
        stripped = row.model_copy(update={"target": remainder})
        return self._injector.apply(
            ConcernInjection(weave_id="__tool_guard__", injections=[stripped]),
            arguments,
        )


__all__ = ["OpenClawToolGuard", "ToolGuardOutcome"]
