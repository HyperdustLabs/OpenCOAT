"""Tests for ``opencoat plugin install <host>`` scaffolding (DX sprint)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest
from opencoat_runtime_cli.commands import plugin_cmd
from opencoat_runtime_cli.main import main as cli_main

EXPECTED_FILES = ("__init__.py", "bootstrap_opencoat.py", "host_adapter.py", "concerns.py")


def _scaffold_dir(tmp_path: Path, host: str) -> Path:
    out = tmp_path / f"opencoat_plugin_{host}"
    rc = cli_main(["--no-banner", "plugin", "install", host, "--out", str(out)])
    assert rc == 0, f"plugin install {host} failed: rc={rc}"
    return out


class TestPluginInstall:
    @pytest.mark.parametrize("host", ["openclaw", "custom"])
    def test_install_writes_full_starter_set(self, tmp_path: Path, host: str) -> None:
        out = _scaffold_dir(tmp_path, host)
        for name in EXPECTED_FILES:
            assert (out / name).exists(), f"missing {name}"
            assert (out / name).stat().st_size > 0, f"{name} is empty"

    @pytest.mark.parametrize("host", ["openclaw", "custom"])
    def test_scaffold_files_are_syntactically_valid_python(self, tmp_path: Path, host: str) -> None:
        """The generated scaffold must parse as Python (no f-string drift)."""
        out = _scaffold_dir(tmp_path, host)
        for name in EXPECTED_FILES:
            text = (out / name).read_text(encoding="utf-8")
            ast.parse(text)  # raises SyntaxError if the template is broken

    @pytest.mark.parametrize("host", ["openclaw", "custom"])
    def test_scaffold_package_is_importable(self, tmp_path: Path, host: str) -> None:
        """Adding the parent dir to ``sys.path`` makes the scaffold importable."""
        out = _scaffold_dir(tmp_path, host)
        parent = str(out.parent)
        sys.path.insert(0, parent)
        pkg_name = out.name
        try:
            mod = __import__(pkg_name)
            assert mod.__doc__ is not None
            assert host in mod.__doc__
        finally:
            sys.path.remove(parent)
            for key in [k for k in sys.modules if k == pkg_name or k.startswith(f"{pkg_name}.")]:
                sys.modules.pop(key, None)

    def test_install_default_out_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Without ``--out`` we land in ``./opencoat_plugin`` relative to cwd."""
        monkeypatch.chdir(tmp_path)
        rc = cli_main(["--no-banner", "plugin", "install", "openclaw"])
        assert rc == 0
        target = tmp_path / "opencoat_plugin"
        for name in EXPECTED_FILES:
            assert (target / name).exists()
        assert "wrote 4 files" in capsys.readouterr().out

    def test_install_blocks_overwrite_without_force(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = _scaffold_dir(tmp_path, "custom")
        capsys.readouterr()
        rc = cli_main(["--no-banner", "plugin", "install", "custom", "--out", str(out)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "already exists" in err
        assert "--force" in err

    def test_install_force_overwrites(self, tmp_path: Path) -> None:
        out = _scaffold_dir(tmp_path, "openclaw")
        sentinel = "# sentinel-edit\n"
        (out / "concerns.py").write_text(sentinel, encoding="utf-8")
        rc = cli_main(
            ["--no-banner", "plugin", "install", "openclaw", "--out", str(out), "--force"]
        )
        assert rc == 0
        body = (out / "concerns.py").read_text(encoding="utf-8")
        assert body != sentinel
        assert "seed_concerns" in body

    def test_install_rejects_unknown_host(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """argparse ``choices`` reject the unknown host with exit code 2."""
        out = tmp_path / "ignored"
        with pytest.raises(SystemExit) as exc:
            cli_main(["--no-banner", "plugin", "install", "nothere", "--out", str(out)])
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_install_partial_failure_writes_nothing(self, tmp_path: Path) -> None:
        """Pre-flight existence check runs before any file write."""
        out = tmp_path / "partial"
        out.mkdir()
        # Pre-populate the second-checked file; nothing else.
        existing = out / "host_adapter.py"
        existing.write_text("# preexisting\n", encoding="utf-8")

        rc = cli_main(["--no-banner", "plugin", "install", "custom", "--out", str(out)])
        assert rc == 1
        # We must NOT have written __init__.py / bootstrap_opencoat.py / concerns.py.
        assert not (out / "__init__.py").exists()
        assert not (out / "bootstrap_opencoat.py").exists()
        assert not (out / "concerns.py").exists()
        # Existing file untouched.
        assert existing.read_text(encoding="utf-8") == "# preexisting\n"


class TestPluginList:
    def test_list_emits_known_hosts(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli_main(["--no-banner", "plugin", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        for name in plugin_cmd._AVAILABLE_HOSTS:
            assert name in out


class TestPluginDisable:
    def test_disable_is_stub_until_post_m6(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli_main(["--no-banner", "plugin", "disable", "some-name"])
        assert rc == 2
        assert "post-M6" in capsys.readouterr().err


class TestScaffoldJoinpointsAreReachable:
    """Pin the scaffold concerns to joinpoints that actually fire.

    Codex P2 on PR #37 flagged that ``on_request_received`` was unreachable
    via the OpenClaw adapter / default event subscription; this test pins
    the reachability invariant for both scaffolds so the regression cannot
    silently return.
    """

    def test_openclaw_concerns_reach_default_subscription(self) -> None:
        from opencoat_runtime_cli.plugin_templates.openclaw.bootstrap_opencoat import (
            DEFAULT_EVENT_NAMES,
        )
        from opencoat_runtime_cli.plugin_templates.openclaw.concerns import seed_concerns
        from opencoat_runtime_host_openclaw.joinpoint_map import OPENCLAW_EVENT_MAP

        reachable = {OPENCLAW_EVENT_MAP[name] for name in DEFAULT_EVENT_NAMES}
        for concern in seed_concerns():
            for jp in concern.pointcut.joinpoints:
                assert jp in reachable, (
                    f"concern {concern.id!r} uses joinpoint {jp!r} which is not "
                    f"emitted by the default OpenClaw event subscription "
                    f"({sorted(reachable)})"
                )

    def test_custom_concerns_reference_catalog_joinpoints(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.concerns import seed_concerns
        from opencoat_runtime_core.joinpoint import JOINPOINT_CATALOG

        for concern in seed_concerns():
            for jp in concern.pointcut.joinpoints:
                assert jp in JOINPOINT_CATALOG, (
                    f"concern {concern.id!r} uses joinpoint {jp!r} which is not "
                    f"in the built-in JOINPOINT_CATALOG"
                )


class TestScaffoldExposesDaemonBackedSurface:
    """The 0.1.0 scaffold ships two install paths: daemon-backed (the
    default, paired with ``opencoat runtime up``) and in-process. The
    daemon-backed path is what the ``opencoat-skill`` demo flow expects.
    These tests pin the public surface so the skill's copy-paste
    instructions can't go stale.
    """

    def test_openclaw_scaffold_exposes_daemon_install_and_legacy_install(self) -> None:
        from opencoat_runtime_cli.plugin_templates.openclaw import bootstrap_opencoat

        # Daemon-backed entry points.
        assert callable(bootstrap_opencoat.install)
        assert callable(bootstrap_opencoat.daemon_client)
        assert bootstrap_opencoat.DEFAULT_DAEMON_URL == "http://127.0.0.1:7878"
        # Legacy in-process path is still available, renamed to make
        # the daemon-vs-embedded choice explicit at the call site.
        assert callable(bootstrap_opencoat.install_in_process)
        assert callable(bootstrap_opencoat.build_runtime)
        assert callable(bootstrap_opencoat.seed_stores)
        # The events the adapter subscribes to are unchanged; pinned by
        # the reachability test below.
        assert bootstrap_opencoat.DEFAULT_EVENT_NAMES == (
            "agent.started",
            "agent.user_message",
            "agent.memory_write",
        )

    def test_custom_scaffold_exposes_daemon_client_helper(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom import bootstrap_opencoat

        assert callable(bootstrap_opencoat.daemon_client)
        assert bootstrap_opencoat.DEFAULT_DAEMON_URL == "http://127.0.0.1:7878"
        # In-process path stays available for tests / scripts.
        assert callable(bootstrap_opencoat.build_runtime_with_adapter)

    def test_openclaw_daemon_client_honours_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from opencoat_runtime_cli.plugin_templates.openclaw import bootstrap_opencoat
        from opencoat_runtime_host_sdk.transport.http import HttpTransport

        monkeypatch.setenv("OPENCOAT_DAEMON_URL", "http://10.0.0.7:9999")
        client = bootstrap_opencoat.daemon_client()
        assert isinstance(client.transport, HttpTransport)
        assert client.transport.endpoint == "http://10.0.0.7:9999/rpc"

    def test_openclaw_daemon_client_explicit_url_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from opencoat_runtime_cli.plugin_templates.openclaw import bootstrap_opencoat

        monkeypatch.setenv("OPENCOAT_DAEMON_URL", "http://from-env:1")
        client = bootstrap_opencoat.daemon_client("http://explicit:2")
        assert client.transport.endpoint == "http://explicit:2/rpc"

    def test_custom_scaffold_imports_without_host_sdk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The custom scaffold must be importable in a runtime-only
        install (no ``opencoat-runtime-host`` on path).

        ``opencoat-runtime`` does not declare ``opencoat-runtime-host``
        as a dependency, so users on a ``pipx install opencoat-runtime``
        topology must still be able to ``import bootstrap_opencoat``
        and use :func:`build_runtime_with_adapter` for the in-process
        path. Only :func:`daemon_client` actually needs the host SDK,
        and pays the import cost lazily.
        """
        # Pretend the host SDK is uninstalled.
        monkeypatch.setitem(sys.modules, "opencoat_runtime_host_sdk", None)
        # Force a re-import so the top-of-file import block re-runs
        # under the simulated missing-package state.
        sys.modules.pop(
            "opencoat_runtime_cli.plugin_templates.custom.bootstrap_opencoat",
            None,
        )

        from opencoat_runtime_cli.plugin_templates.custom import bootstrap_opencoat

        # In-process path still works — that's the whole point of the
        # lazy import. We don't actually call build_runtime_with_adapter
        # here because the runtime + LLM stub paths are exercised
        # elsewhere; we just want to prove the module loaded.
        assert callable(bootstrap_opencoat.build_runtime_with_adapter)
        assert callable(bootstrap_opencoat.build_runtime)

        # daemon_client is still exposed (for type discovery / docs),
        # but calling it without the host SDK fails *at call time*,
        # not at import time, with the same error the user would get
        # from ``from opencoat_runtime_host_sdk import Client``.
        with pytest.raises((ModuleNotFoundError, ImportError)):
            bootstrap_opencoat.daemon_client()

    def test_openclaw_daemon_runtime_proxy_forwards_to_client(self) -> None:
        """The :class:`_DaemonRuntime` proxy must satisfy ``RuntimeLike``
        and forward every :meth:`on_joinpoint` call to ``client.emit``.
        """
        from opencoat_runtime_cli.plugin_templates.openclaw.bootstrap_opencoat import (
            _DaemonRuntime,
        )
        from opencoat_runtime_host_openclaw.hooks import RuntimeLike

        captured: list[tuple[Any, dict[str, Any]]] = []

        class _FakeClient:
            def emit(self, jp, **kw):  # type: ignore[no-untyped-def]
                captured.append((jp, kw))
                return "sentinel"

        proxy = _DaemonRuntime(_FakeClient())  # type: ignore[arg-type]
        # Pin both the structural Protocol satisfaction and the
        # forwarding semantics — these are the two things install_hooks
        # relies on when ``install()`` wires the proxy in for the
        # daemon-backed path.
        assert isinstance(proxy, RuntimeLike)
        out = proxy.on_joinpoint("jp-fake", context={"k": "v"}, return_none_when_empty=True)  # type: ignore[arg-type]
        assert out == "sentinel"
        assert captured == [("jp-fake", {"context": {"k": "v"}, "return_none_when_empty": True})]


class TestPluginInstallNextOutput:
    """Pin the post-install ``Next:`` guidance so users see the
    daemon-first flow that matches the ``opencoat-skill`` demo, not
    the legacy in-process call.
    """

    def test_openclaw_next_steps_lead_with_runtime_up(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()
        _scaffold_dir(tmp_path, "openclaw")
        out = capsys.readouterr().out
        assert "opencoat runtime up" in out
        assert "opencoat concern import --demo" in out
        assert "bootstrap_opencoat.install" in out
        # The in-process path is still mentioned as an alternative.
        assert "install_in_process" in out

    def test_custom_next_steps_lead_with_runtime_up(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()
        _scaffold_dir(tmp_path, "custom")
        out = capsys.readouterr().out
        assert "opencoat runtime up" in out
        assert "daemon_client" in out
        assert "client.emit" in out
        # The scaffold now ships a working CustomHostAdapter, so the
        # Next: output advertises that rather than "fill in the stubs".
        assert "EVENT_TO_JOINPOINT" in out
        assert "stub" not in out.lower()


class TestCustomScaffoldHostAdapterFilled:
    """The custom scaffold's ``host_adapter.py`` ships with both halves
    of the :class:`HostAdapter` contract pre-implemented, so a user can
    ``opencoat plugin install custom`` → build runtime → emit event →
    see the injection fold into their host context **without editing
    the scaffold first**.

    This block pins:

    * the default event-name → joinpoint table is non-empty and points
      only at joinpoints that actually exist in ``JOINPOINT_CATALOG``;
    * ``map_host_event`` walks every default event-name key
      (``type`` / ``name`` / ``event`` / ``event_name``) and uses the
      first value that appears in the map — so mixed envelopes still
      resolve — and drops events with no mapped name (the runtime treats
      that as "ignore");
    * ``apply_injection`` deep-copies the host context, walks dotted
      target paths, creates missing intermediate dicts, and dispatches
      to the right weaving mode (append vs overwrite);
    * the seeded concern fires end-to-end against an in-proc runtime —
      i.e. the scaffold is genuinely "import + run".
    """

    def test_event_to_joinpoint_map_is_non_empty_and_catalog_clean(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            EVENT_TO_JOINPOINT,
        )
        from opencoat_runtime_core.joinpoint import JOINPOINT_CATALOG

        assert EVENT_TO_JOINPOINT, "default event map must not be empty"
        for host_event, jp_name in EVENT_TO_JOINPOINT.items():
            assert isinstance(host_event, str) and host_event
            assert JOINPOINT_CATALOG.get(jp_name) is not None, (
                f"{host_event!r} maps to {jp_name!r} which is not in JOINPOINT_CATALOG"
            )

    @pytest.mark.parametrize("key", ["type", "name", "event", "event_name"])
    def test_map_host_event_recognises_all_default_name_keys(self, key: str) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter()
        jp = adapter.map_host_event({key: "agent.user_message", "text": "hi"})
        assert jp is not None
        assert jp.name == "on_user_input"
        assert jp.host == "custom"
        # Non-envelope fields are mirrored into payload so pointcut
        # strategies see the host's full event shape.
        assert jp.payload == {"text": "hi"}

    def test_map_host_event_skips_unmapped_earlier_keys_for_mixed_envelopes(
        self,
    ) -> None:
        """P2 from Codex review: coarse ``type`` must not hide fine ``event_name``."""
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter()
        jp = adapter.map_host_event(
            {
                "type": "audit",
                "event_name": "agent.user_message",
                "text": "hi",
            }
        )
        assert jp is not None
        assert jp.name == "on_user_input"
        assert jp.payload == {"text": "hi"}

    def test_map_host_event_returns_none_for_unknown_event_name(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter()
        assert adapter.map_host_event({"type": "agent.bogus_event"}) is None
        # No recognised name key at all → also None, not crash.
        assert adapter.map_host_event({"payload": {"k": "v"}}) is None

    def test_map_host_event_honours_explicit_payload_field(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter()
        jp = adapter.map_host_event(
            {
                "type": "before_tool_call",
                "agent_session_id": "sess-1",
                "host_round_id": "turn-2",
                "payload": {"content": "shell.exec rm -rf /tmp/x"},
            }
        )
        assert jp is not None
        assert jp.name == "before_tool_call"
        assert jp.agent_session_id == "sess-1"
        assert jp.host_round_id == "turn-2"
        assert jp.payload == {"content": "shell.exec rm -rf /tmp/x"}

    def test_map_host_event_rejects_non_dict_events(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter()
        with pytest.raises(ValueError, match="dict"):
            adapter.map_host_event(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_map_host_events_drops_none_and_yields_rest(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter()
        events = [
            {"type": "agent.user_message", "text": "hi"},
            {"type": "agent.totally_unknown"},
            {"type": "agent.memory_write", "key": "k", "value": "v"},
        ]
        names = [jp.name for jp in adapter.map_host_events(events)]
        assert names == ["on_user_input", "before_memory_write"]

    def test_apply_injection_appends_on_insert_creating_path(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )
        from opencoat_runtime_protocol import (
            ConcernInjection,
            Injection,
            WeavingOperation,
        )

        adapter = CustomHostAdapter()
        inj = ConcernInjection(
            weave_id="t-1",
            injections=[
                Injection(
                    concern_id="c-demo",
                    target="runtime_prompt.active_concerns",
                    content="be precise",
                    mode=WeavingOperation.INSERT,
                )
            ],
        )
        # Empty starting context — the adapter creates the nested path.
        out = adapter.apply_injection(inj, {})
        assert out == {"runtime_prompt": {"active_concerns": "be precise"}}

    def test_apply_injection_appends_with_newline_on_non_empty_string(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )
        from opencoat_runtime_protocol import (
            ConcernInjection,
            Injection,
            WeavingOperation,
        )

        adapter = CustomHostAdapter()
        inj = ConcernInjection(
            weave_id="t-2",
            injections=[
                Injection(
                    concern_id="c-demo",
                    target="response.body.prefix",
                    content="[OpenCOAT]",
                    mode=WeavingOperation.INSERT,
                )
            ],
        )
        ctx = {"response": {"body": {"prefix": "hello"}}}
        out = adapter.apply_injection(inj, ctx)
        assert out == {"response": {"body": {"prefix": "hello\n[OpenCOAT]"}}}
        # Source context untouched.
        assert ctx == {"response": {"body": {"prefix": "hello"}}}

    def test_apply_injection_overwrites_on_block_modes(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )
        from opencoat_runtime_protocol import (
            ConcernInjection,
            Injection,
            WeavingOperation,
        )

        adapter = CustomHostAdapter()
        inj = ConcernInjection(
            weave_id="t-3",
            injections=[
                Injection(
                    concern_id="c-guard",
                    target="tool_call.arguments",
                    content="refused: rm -rf",
                    mode=WeavingOperation.BLOCK,
                )
            ],
        )
        ctx = {"tool_call": {"arguments": "rm -rf /"}}
        out = adapter.apply_injection(inj, ctx)
        assert out == {"tool_call": {"arguments": "refused: rm -rf"}}

    def test_apply_injection_skips_rows_with_empty_target(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )
        from opencoat_runtime_protocol import (
            ConcernInjection,
            Injection,
            WeavingOperation,
        )

        adapter = CustomHostAdapter()
        inj = ConcernInjection(
            weave_id="t-4",
            injections=[
                Injection(
                    concern_id="c-empty",
                    target="",
                    content="ignored",
                    mode=WeavingOperation.INSERT,
                ),
                Injection(
                    concern_id="c-real",
                    target="prompt.note",
                    content="kept",
                    mode=WeavingOperation.INSERT,
                ),
            ],
        )
        out = adapter.apply_injection(inj, {})
        assert out == {"prompt": {"note": "kept"}}

    def test_event_map_can_be_overridden_per_instance(self) -> None:
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        adapter = CustomHostAdapter(
            host_name="my-framework",
            event_map={"chat.message_received": "on_user_input"},
        )
        assert adapter.host_name == "my-framework"
        jp = adapter.map_host_event({"type": "chat.message_received", "text": "hi"})
        assert jp is not None
        assert jp.name == "on_user_input"
        assert jp.host == "my-framework"

        # Default mappings no longer apply because we replaced the table wholesale.
        assert adapter.map_host_event({"type": "agent.user_message"}) is None

    def test_seeded_demo_concern_fires_end_to_end_against_real_runtime(self) -> None:
        """The cornerstone test: scaffold imports → seed a runtime →
        ``map_host_event`` → ``runtime.on_joinpoint`` → ``apply_injection``
        produces a context change visible from the demo concern. This
        is the "import and run" promise the scaffold makes — no edits
        required.
        """
        from opencoat_runtime_cli.plugin_templates.custom import bootstrap_opencoat
        from opencoat_runtime_cli.plugin_templates.custom.host_adapter import (
            CustomHostAdapter,
        )

        runtime = bootstrap_opencoat.build_runtime()
        bootstrap_opencoat.seed_stores(runtime)
        adapter = CustomHostAdapter()

        event = {"type": "agent.user_message", "text": "hello runtime"}
        jp = adapter.map_host_event(event)
        assert jp is not None and jp.name == "on_user_input"

        injection = runtime.on_joinpoint(jp)
        assert injection is not None
        assert injection.injections, "demo concern must produce ≥1 injection"

        host_ctx: dict[str, Any] = {}
        new_ctx = adapter.apply_injection(injection, host_ctx)
        # The demo concern writes to runtime_prompt.active_concerns;
        # the scaffold's apply_injection should have built that path.
        assert "runtime_prompt" in new_ctx
        assert "active_concerns" in new_ctx["runtime_prompt"]
        active = new_ctx["runtime_prompt"]["active_concerns"]
        assert "OpenCOAT" in active or "runtime" in active.lower()
