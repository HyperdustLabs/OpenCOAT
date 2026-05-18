"""Tests for :class:`OpenClawToolGuard` and :class:`ToolGuardOutcome` (M5 #30)."""

from __future__ import annotations

import copy

import pytest
from opencoat_runtime_host_openclaw import (
    OpenClawAdapter,
    OpenClawAdapterConfig,
    OpenClawInjector,
    OpenClawToolGuard,
    ToolGuardOutcome,
)
from opencoat_runtime_protocol import ConcernInjection, Injection, WeavingOperation

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _inj(*rows: Injection) -> ConcernInjection:
    return ConcernInjection(weave_id="t-tool-guard", injections=list(rows))


def _row(
    target: str,
    mode: WeavingOperation | str,
    content: str = "policy",
    concern_id: str = "c-x",
) -> Injection:
    return Injection(concern_id=concern_id, target=target, mode=mode, content=content)


@pytest.fixture
def guard() -> OpenClawToolGuard:
    return OpenClawToolGuard()


# ---------------------------------------------------------------------------
# block
# ---------------------------------------------------------------------------


class TestBlockSemantics:
    """A BLOCK row anywhere under ``tool_call.*`` refuses the whole call."""

    def test_block_on_arguments_wildcard_marks_blocked(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "shell", "arguments": {"cmd": "rm -rf /"}},
            _inj(
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.BLOCK,
                    "destructive shell call",
                )
            ),
        )
        assert outcome.blocked is True
        assert outcome.block_reason == "destructive shell call"
        # Arguments preserved verbatim so audit can see what was attempted.
        assert outcome.arguments == {"cmd": "rm -rf /"}

    def test_block_on_tool_call_wildcard_marks_blocked(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "shell", "arguments": {"cmd": "ls"}},
            _inj(_row("tool_call.*", WeavingOperation.BLOCK, "denied by policy")),
        )
        assert outcome.blocked is True
        assert outcome.block_reason == "denied by policy"

    def test_block_on_specific_arg_path_still_blocks(self, guard: OpenClawToolGuard) -> None:
        """BLOCK is whole-call by definition — a per-arg target still
        refuses the call (selectively blocking one argument isn't a
        coherent dispatch state)."""
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/etc/passwd"}},
            _inj(
                _row(
                    "tool_call.arguments.path",
                    WeavingOperation.BLOCK,
                    "no system files",
                )
            ),
        )
        assert outcome.blocked is True
        assert outcome.block_reason == "no system files"

    def test_suppress_and_escalate_modes_also_block(self, guard: OpenClawToolGuard) -> None:
        for mode in (WeavingOperation.SUPPRESS, WeavingOperation.ESCALATE):
            outcome = guard.guard(
                {"name": "shell", "arguments": {"cmd": "x"}},
                _inj(_row("tool_call.arguments.*", mode, f"{mode.value} fired")),
            )
            assert outcome.blocked is True, mode
            assert outcome.block_reason == f"{mode.value} fired"

    def test_multiple_block_reasons_are_newline_joined(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "shell", "arguments": {"cmd": "x"}},
            _inj(
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.BLOCK,
                    "first reason",
                    concern_id="c-1",
                ),
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.BLOCK,
                    "second reason",
                    concern_id="c-2",
                ),
            ),
        )
        assert outcome.blocked is True
        assert outcome.block_reason == "first reason\nsecond reason"


# ---------------------------------------------------------------------------
# mutate
# ---------------------------------------------------------------------------


class TestMutateSemantics:
    """REPLACE / REWRITE / COMPRESS modes rewrite individual args."""

    def test_replace_on_specific_arg_rewrites_only_that_arg(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/secret.txt", "mode": "r"}},
            _inj(
                _row(
                    "tool_call.arguments.path",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                )
            ),
        )
        assert outcome.blocked is False
        assert outcome.arguments == {"path": "[REDACTED]", "mode": "r"}

    def test_replace_wildcard_rewrites_every_arg(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x", "mode": "r"}},
            _inj(
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                )
            ),
        )
        assert outcome.blocked is False
        assert outcome.arguments == {"path": "[REDACTED]", "mode": "[REDACTED]"}

    def test_rewrite_mode_overwrites(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"query": "hello"}},
            _inj(
                _row(
                    "tool_call.arguments.query",
                    WeavingOperation.REWRITE,
                    "hello world",
                )
            ),
        )
        assert outcome.arguments == {"query": "hello world"}

    def test_replace_on_bare_tool_call_arguments_redacts_all_keys(
        self, guard: OpenClawToolGuard
    ) -> None:
        """``tool_call.arguments`` (no leaf) with REPLACE means "redact
        the whole argument map" — handled as a trailing wildcard so
        per-key semantics apply instead of overwriting the dict with a
        string."""
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x", "mode": "r"}},
            _inj(
                _row(
                    "tool_call.arguments",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                )
            ),
        )
        assert outcome.arguments == {"path": "[REDACTED]", "mode": "[REDACTED]"}


class TestOverwriteScopeGuard:
    """Codex P1 on PR #30 — overwrite rows outside ``tool_call.arguments``
    must not corrupt the ``arguments`` dict.
    """

    def test_replace_on_tool_call_wildcard_does_not_clobber_arguments(
        self, guard: OpenClawToolGuard
    ) -> None:
        """``tool_call.*`` REPLACE used to overwrite the whole
        ``tool_call`` dict (including ``arguments``), leaving a string
        in :attr:`ToolGuardOutcome.arguments`. Now silently dropped."""
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(_row("tool_call.*", WeavingOperation.REPLACE, "stomped")),
        )
        assert isinstance(outcome.arguments, dict)
        assert outcome.arguments == {"path": "/x"}
        assert outcome.notes == []

    def test_replace_on_tool_call_name_is_dropped(self, guard: OpenClawToolGuard) -> None:
        """Renaming the tool itself is not a coherent dispatch state."""
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(_row("tool_call.name", WeavingOperation.REPLACE, "evil")),
        )
        assert outcome.arguments == {"path": "/x"}
        assert outcome.notes == []

    def test_rewrite_on_bare_tool_call_is_dropped(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(_row("tool_call.something", WeavingOperation.REWRITE, "x")),
        )
        assert outcome.arguments == {"path": "/x"}

    def test_overwrite_drop_does_not_block_other_rows(self, guard: OpenClawToolGuard) -> None:
        """Dropping an out-of-scope overwrite row must not prevent
        valid rows in the same injection from firing."""
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(
                _row(
                    "tool_call.name",
                    WeavingOperation.REPLACE,
                    "ignored",
                    concern_id="c-drop",
                ),
                _row(
                    "tool_call.arguments.path",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                    concern_id="c-keep",
                ),
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.WARN,
                    "audit",
                    concern_id="c-note",
                ),
            ),
        )
        assert outcome.arguments == {"path": "[REDACTED]"}
        assert outcome.notes == ["audit"]


# ---------------------------------------------------------------------------
# annotate
# ---------------------------------------------------------------------------


class TestAnnotateSemantics:
    """INSERT / WARN / ANNOTATE / VERIFY / DEFER → notes, no arg mutation."""

    @pytest.mark.parametrize(
        "mode",
        [
            WeavingOperation.INSERT,
            WeavingOperation.ANNOTATE,
            WeavingOperation.WARN,
            WeavingOperation.VERIFY,
            WeavingOperation.DEFER,
        ],
    )
    def test_append_modes_accumulate_notes(
        self, guard: OpenClawToolGuard, mode: WeavingOperation
    ) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(_row("tool_call.arguments.*", mode, "audit me")),
        )
        assert outcome.blocked is False
        assert outcome.arguments == {"path": "/x"}
        assert outcome.notes == ["audit me"]

    def test_multiple_notes_preserve_order(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.INSERT,
                    "first",
                    concern_id="c-1",
                ),
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.WARN,
                    "second",
                    concern_id="c-2",
                ),
            ),
        )
        assert outcome.notes == ["first", "second"]


# ---------------------------------------------------------------------------
# mixed
# ---------------------------------------------------------------------------


class TestMixedAndFiltering:
    def test_non_tool_call_rows_are_ignored(self, guard: OpenClawToolGuard) -> None:
        """Rows for runtime_prompt / response targets fall through —
        those belong on :meth:`OpenClawAdapter.apply_injection`."""
        outcome = guard.guard(
            {"name": "shell", "arguments": {"cmd": "ls"}},
            _inj(
                _row(
                    "runtime_prompt.output_format",
                    WeavingOperation.INSERT,
                    "ignored",
                ),
                _row(
                    "response.text",
                    WeavingOperation.REPLACE,
                    "ignored",
                ),
            ),
        )
        assert outcome.blocked is False
        assert outcome.arguments == {"cmd": "ls"}
        assert outcome.notes == []

    def test_block_plus_mutate_block_wins_but_mutations_still_recorded(
        self, guard: OpenClawToolGuard
    ) -> None:
        """A BLOCK row sets ``blocked``, but earlier REPLACE rows still
        reflect in ``arguments`` so the audit trail keeps a complete
        picture of what the guard *would* have dispatched."""
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/secret"}},
            _inj(
                _row(
                    "tool_call.arguments.path",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                    concern_id="c-redact",
                ),
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.BLOCK,
                    "policy denied",
                    concern_id="c-block",
                ),
            ),
        )
        assert outcome.blocked is True
        assert outcome.block_reason == "policy denied"
        assert outcome.arguments == {"path": "[REDACTED]"}

    def test_empty_injection_is_passthrough(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "open", "arguments": {"path": "/x"}},
            ConcernInjection(weave_id="t"),
        )
        assert outcome == ToolGuardOutcome(
            blocked=False,
            block_reason=None,
            arguments={"path": "/x"},
            notes=[],
        )

    def test_input_tool_call_is_not_mutated(self, guard: OpenClawToolGuard) -> None:
        tool_call = {"name": "open", "arguments": {"path": "/x"}}
        snapshot = copy.deepcopy(tool_call)
        guard.guard(
            tool_call,
            _inj(
                _row(
                    "tool_call.arguments.path",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                )
            ),
        )
        assert tool_call == snapshot

    def test_missing_arguments_key_defaults_to_empty_dict(self, guard: OpenClawToolGuard) -> None:
        outcome = guard.guard(
            {"name": "ping"},
            _inj(_row("tool_call.*", WeavingOperation.BLOCK, "no")),
        )
        assert outcome.blocked is True
        assert outcome.arguments == {}


# ---------------------------------------------------------------------------
# wire-mode strings (JSON round-trip)
# ---------------------------------------------------------------------------


class TestWireModeStrings:
    """``mode`` round-trips through JSON as plain strings — accept both."""

    def test_string_block_mode(self, guard: OpenClawToolGuard) -> None:
        inj = ConcernInjection.model_validate(
            {
                "weave_id": "t",
                "injections": [
                    {
                        "concern_id": "c-1",
                        "target": "tool_call.arguments.*",
                        "mode": "block",
                        "content": "denied",
                    }
                ],
            }
        )
        outcome = guard.guard({"name": "x", "arguments": {"a": 1}}, inj)
        assert outcome.blocked is True
        assert outcome.block_reason == "denied"

    def test_string_replace_mode(self, guard: OpenClawToolGuard) -> None:
        inj = ConcernInjection.model_validate(
            {
                "weave_id": "t",
                "injections": [
                    {
                        "concern_id": "c-1",
                        "target": "tool_call.arguments.path",
                        "mode": "replace",
                        "content": "[REDACTED]",
                    }
                ],
            }
        )
        outcome = guard.guard({"name": "open", "arguments": {"path": "/x"}}, inj)
        assert outcome.arguments == {"path": "[REDACTED]"}


# ---------------------------------------------------------------------------
# adapter integration
# ---------------------------------------------------------------------------


class TestAdapterIntegration:
    def test_guard_tool_call_delegates_to_tool_guard(self) -> None:
        adapter = OpenClawAdapter()
        outcome = adapter.guard_tool_call(
            {"name": "shell", "arguments": {"cmd": "rm -rf /"}},
            _inj(
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.BLOCK,
                    "destructive",
                )
            ),
        )
        assert isinstance(outcome, ToolGuardOutcome)
        assert outcome.blocked is True
        assert outcome.block_reason == "destructive"

    def test_adapter_config_propagates_to_tool_guard(self) -> None:
        """Tool-guard should never touch ``runtime_prompt.*`` rows even
        when prompt injection is disabled on the adapter — they're
        outside the tool_call.* scope anyway."""
        adapter = OpenClawAdapter(OpenClawAdapterConfig(inject_into_runtime_prompt=False))
        outcome = adapter.guard_tool_call(
            {"name": "open", "arguments": {"path": "/x"}},
            _inj(
                _row(
                    "tool_call.arguments.path",
                    WeavingOperation.REPLACE,
                    "[REDACTED]",
                ),
                _row(
                    "runtime_prompt.output_format",
                    WeavingOperation.INSERT,
                    "ignored",
                ),
            ),
        )
        assert outcome.blocked is False
        assert outcome.arguments == {"path": "[REDACTED]"}
        assert outcome.notes == []

    def test_shared_injector_with_adapter(self) -> None:
        """Ensure the same injector instance can be reused — config and
        wildcard semantics should be identical for ``apply_injection``
        and ``guard_tool_call``."""
        injector = OpenClawInjector()
        guard = OpenClawToolGuard(injector)
        outcome = guard.guard(
            {"name": "open", "arguments": {"a": "x", "b": "y"}},
            _inj(
                _row(
                    "tool_call.arguments.*",
                    WeavingOperation.REPLACE,
                    "*",
                )
            ),
        )
        assert outcome.arguments == {"a": "*", "b": "*"}
