"""Tests for :class:`~opencoat_runtime_daemon.daemon.Daemon` lifecycle (M4 PR-20)."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import pytest
from opencoat_runtime_daemon import Daemon, DaemonAlreadyStartedError
from opencoat_runtime_daemon._pidfile import PidFileError
from opencoat_runtime_daemon.config import load_config


def _http_cfg(tmp_path: Path | None = None):  # type: ignore[no-untyped-def]
    cfg = load_config()
    # Bundled default already enables HTTP on 7878. Switch to OS-assigned
    # port so this test (and any parallel one) doesn't collide.
    cfg.ipc.http.enabled = True
    object.__setattr__(cfg.ipc.http, "host", "127.0.0.1")
    object.__setattr__(cfg.ipc.http, "port", 0)
    object.__setattr__(cfg.ipc.http, "path", "/rpc")
    return cfg


def _no_http_cfg():  # type: ignore[no-untyped-def]
    """Load the bundled default config but turn HTTP off.

    Most lifecycle tests exercise pid-file / signal / reload behaviour
    and do not care about the IPC listener; explicitly disabling HTTP
    keeps them from binding the default 7878 (and TIME_WAITing it for
    follow-up tests).
    """
    cfg = load_config()
    cfg.ipc.http.enabled = False
    return cfg


def test_start_stop_no_http(tmp_path: Path) -> None:
    # Bundled default ships ``ipc.http.enabled: true`` so a zero-config
    # ``opencoat runtime up`` is reachable from the CLI and the host SDK
    # (see ADR 0005). Embedded users who want a pure in-proc daemon
    # disable it explicitly — which is what ``_no_http_cfg`` does.
    cfg = _no_http_cfg()
    pid = tmp_path / "opencoat.pid"
    d = Daemon(cfg, env={}, pid_file=pid)
    d.start()
    try:
        assert pid.exists()
        assert pid.read_text().strip() == str(os.getpid())
        assert d.http_server is None
        # No HTTP — handler still wired in-proc.
        out = d.runtime_handler.handle({"jsonrpc": "2.0", "id": 1, "method": "health.ping"})
        assert out == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}
    finally:
        d.stop()
    assert not pid.exists()


def test_stop_is_idempotent(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    d.start()
    d.stop()
    d.stop()  # second call is a no-op


def test_start_twice_raises(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    d.start()
    try:
        with pytest.raises(DaemonAlreadyStartedError):
            d.start()
    finally:
        d.stop()


def test_pid_file_collision_blocks_start(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    pid = tmp_path / "opencoat.pid"
    # Reserve the path with PID 1 (always alive on POSIX).
    pid.write_text("1\n")
    d = Daemon(cfg, env={}, pid_file=pid)
    with pytest.raises(PidFileError):
        d.start()
    # PID file untouched.
    assert pid.read_text().strip() == "1"


def test_resolve_pid_path_prefers_explicit_override(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    explicit = tmp_path / "explicit.pid"
    assert Daemon._resolve_pid_path(cfg, explicit) == explicit


def test_resolve_pid_path_uses_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    target = tmp_path / "env.pid"
    monkeypatch.setenv("OPENCOAT_PID_FILE", str(target))
    assert Daemon._resolve_pid_path(cfg, None) == target


def test_resolve_pid_path_returns_none_without_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _no_http_cfg()
    monkeypatch.delenv("OPENCOAT_PID_FILE", raising=False)
    assert Daemon._resolve_pid_path(cfg, None) is None


def test_acquire_creates_parent_directory(tmp_path: Path) -> None:
    """Daemon.start() should ``mkdir -p`` the pid file's parent dir."""
    cfg = _no_http_cfg()
    pid = tmp_path / "nested" / "dir" / "opencoat.pid"
    assert not pid.parent.exists()
    d = Daemon(cfg, env={}, pid_file=pid)
    d.start()
    try:
        assert pid.parent.is_dir()
        assert pid.exists()
    finally:
        d.stop()


def test_http_endpoint_serves_jsonrpc(tmp_path: Path) -> None:
    cfg = _http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    d.start()
    try:
        assert d.http_server is not None
        time.sleep(0.05)
        host, port = d.http_server.host, d.http_server.port
        conn = HTTPConnection(host, port, timeout=5)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "health.ping"}).encode()
        conn.request(
            "POST",
            "/rpc",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        resp = conn.getresponse()
        assert resp.status == HTTPStatus.OK
        data = json.loads(resp.read())
        assert data["result"]["ok"] is True
        conn.close()
    finally:
        d.stop()


def test_reload_swaps_runtime_without_restarting_socket(tmp_path: Path) -> None:
    cfg = _http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    d.start()
    try:
        assert d.http_server is not None
        time.sleep(0.05)
        old_handler = d.runtime_handler
        port = d.http_server.port

        d.reload()
        new_handler = d.runtime_handler
        assert new_handler is not old_handler
        # Same listening port.
        assert d.http_server.port == port

        # And the socket is still serving the *new* handler.
        conn = HTTPConnection(d.http_server.host, port, timeout=5)
        body = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "health.ping"}).encode()
        conn.request(
            "POST",
            "/rpc",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        resp = conn.getresponse()
        assert resp.status == HTTPStatus.OK
        conn.close()
    finally:
        d.stop()


def test_reload_heartbeat_ticks_current_runtime(tmp_path: Path) -> None:
    """After reload, the scheduler must tick the new runtime, not the closed one."""
    cfg = _no_http_cfg()
    cfg.runtime.loops.heartbeat_enabled = True
    cfg.runtime.loops.heartbeat_interval_seconds = 3600.0
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    d.start()
    try:
        old_runtime = d._built.runtime
        d.reload()
        new_runtime = d._built.runtime
        assert new_runtime is not old_runtime
        with (
            patch.object(old_runtime, "tick") as old_tick,
            patch.object(new_runtime, "tick") as new_tick,
        ):
            d._heartbeat_tick()
        old_tick.assert_not_called()
        new_tick.assert_called_once()
    finally:
        d.stop()


def test_reload_before_start_raises(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    with pytest.raises(RuntimeError):
        d.reload()


def test_run_until_signal_drains_on_sigterm(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    pid = tmp_path / "opencoat.pid"
    d = Daemon(cfg, env={}, pid_file=pid)

    # We're not in the test's main thread, so signal.signal() will
    # raise inside run_until_signal — instead trigger the same drain
    # path via stop_event from a background timer.
    timer = threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGUSR1))

    received: list[int] = []
    original = signal.getsignal(signal.SIGUSR1)

    def _record(signum: int, _frame: object) -> None:
        received.append(signum)
        d.stop()

    signal.signal(signal.SIGUSR1, _record)
    try:
        d.start()
        timer.start()
        # wait() returns True once stop() runs.
        assert d.wait(timeout=5)
        assert received == [signal.SIGUSR1]
        assert not pid.exists()
    finally:
        signal.signal(signal.SIGUSR1, original)
        timer.cancel()


def test_context_manager_round_trip(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    pid = tmp_path / "opencoat.pid"
    with Daemon(cfg, env={}, pid_file=pid):
        assert pid.exists()
    assert not pid.exists()


def test_runtime_handler_property_raises_before_start(tmp_path: Path) -> None:
    cfg = _no_http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")
    with pytest.raises(RuntimeError):
        _ = d.runtime_handler


def test_restart_after_stop_resets_stop_event(tmp_path: Path) -> None:
    """Codex P2 on PR-20: ``stop()`` sets ``_stop_event``; ``start()``
    must clear it so the next ``wait()`` blocks instead of returning
    immediately.
    """
    cfg = _no_http_cfg()
    d = Daemon(cfg, env={}, pid_file=tmp_path / "opencoat.pid")

    d.start()
    d.stop()
    # Confirm the previous lifecycle's stop_event would otherwise
    # short-circuit wait().
    assert d.wait(timeout=0) is True

    d.start()
    try:
        # New lifecycle: wait must time out instead of returning
        # immediately. ~50 ms is plenty without slowing the suite down.
        t0 = time.monotonic()
        returned = d.wait(timeout=0.05)
        elapsed = time.monotonic() - t0
        assert returned is False
        assert elapsed >= 0.04
    finally:
        d.stop()


def test_concurrent_daemon_instances_share_pid_file_rejection(tmp_path: Path) -> None:
    """Two ``Daemon`` instances on the same PID path within one process
    must not both start.
    """
    cfg = _no_http_cfg()
    pid = tmp_path / "opencoat.pid"
    first = Daemon(cfg, env={}, pid_file=pid)
    second = Daemon(cfg, env={}, pid_file=pid)
    first.start()
    try:
        with pytest.raises(PidFileError):
            second.start()
        # Second instance's resources were rolled back.
        assert second.http_server is None
        # First holder still owns the file.
        assert pid.read_text().strip() == str(os.getpid())
    finally:
        first.stop()
    assert not pid.exists()
