"""Top-level :class:`Daemon` — composes Runtime + IPC + lifecycle (M4 PR-20).

``Daemon`` owns the runtime lifecycle for the long-running ``OPENCOAT``
process:

* :meth:`start` builds the runtime via :func:`build_runtime`, opens the
  configured IPC servers (HTTP today), and writes a PID file.
* :meth:`stop` is idempotent — shuts down the HTTP server, closes
  sqlite handles, releases the PID file.
* :meth:`reload` swaps the runtime in place (drain → rebuild) without
  dropping the listening socket.
* :meth:`run_until_signal` installs ``SIGTERM`` / ``SIGINT`` handlers
  on the **main thread** and blocks until one fires, then drains.

Threading model: the HTTP server runs on a background thread so the
main thread can sit in :meth:`wait` (or in
``signal.pause()``-equivalent) and stay responsive to signals. The
foreground thread never touches sqlite directly.
"""

from __future__ import annotations

import contextlib
import logging
import signal
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._pidfile import PidFile, PidFileError
from .config.loader import DaemonConfig
from .ipc.http_server import HttpServer
from .ipc.jsonrpc_dispatch import JsonRpcHandler
from .runtime_builder import BuiltRuntime, build_runtime, warm_persistent_stores
from .scheduler import Scheduler

logger = logging.getLogger("opencoat_runtime_daemon")

_DRAIN_TIMEOUT_SECONDS = 5.0


class DaemonAlreadyStartedError(RuntimeError):
    """Raised when :meth:`Daemon.start` is called twice on the same instance."""


class Daemon:
    """Composes a :class:`OpenCOATRuntime` with IPC + signal-driven lifecycle.

    Single-instance per process — call :meth:`run_until_signal` to
    block the main thread, or :meth:`start` / :meth:`stop` directly
    from tests.
    """

    def __init__(
        self,
        config: DaemonConfig,
        *,
        env: Mapping[str, str] | None = None,
        pid_file: str | Path | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._pid_file_path = self._resolve_pid_path(config, pid_file)
        self._pid_file: PidFile | None = None
        self._built: BuiltRuntime | None = None
        self._handler: JsonRpcHandler | None = None
        self._http: HttpServer | None = None
        self._http_thread: threading.Thread | None = None
        self._scheduler: Scheduler | None = None
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._started = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    @property
    def config(self) -> DaemonConfig:
        return self._config

    @property
    def runtime_handler(self) -> JsonRpcHandler:
        if self._handler is None:
            raise RuntimeError("Daemon is not started")
        return self._handler

    @property
    def http_server(self) -> HttpServer | None:
        return self._http

    @property
    def pid_file_path(self) -> Path | None:
        return self._pid_file_path

    def start(self) -> None:
        """Build runtime, mount IPC, write PID. Idempotent only once."""
        with self._state_lock:
            if self._started:
                raise DaemonAlreadyStartedError("Daemon.start() already called")
            self._started = True
            # Clear any stop signal left over from a previous lifecycle
            # — otherwise wait()/run_until_signal() on a re-started
            # Daemon would return immediately (Codex P2 on PR-20).
            self._stop_event.clear()
            try:
                self._acquire_pid_file()
                self._built = build_runtime(self._config, env=self._env)
                warm_persistent_stores(self._built.runtime)
                self._handler = JsonRpcHandler(
                    self._built.runtime,
                    llm_info=self._built.llm_info,
                )
                self._maybe_start_http()
                self._maybe_start_scheduler()
                logger.info(
                    "OpenCOAT daemon started (llm=%s, http=%s)",
                    self._built.llm_label,
                    self._http_endpoint_str(),
                )
            except BaseException:
                # Roll back any partial state.
                self._teardown_locked()
                raise

    def stop(self) -> None:
        """Idempotent teardown — drains HTTP, closes runtime, releases PID."""
        with self._state_lock:
            if not self._started:
                return
            self._teardown_locked()
        self._stop_event.set()

    def reload(self) -> None:
        """Drain runtime, rebuild from current config, keep the socket up."""
        with self._state_lock:
            if not self._started:
                raise RuntimeError("Daemon is not started")
            old_built = self._built
            new_built = build_runtime(self._config, env=self._env)
            warm_persistent_stores(new_built.runtime)
            new_handler = JsonRpcHandler(new_built.runtime, llm_info=new_built.llm_info)
            # Swap before closing the old runtime so in-flight RPCs that
            # already grabbed the handler reference keep working; new
            # arrivals immediately see the new runtime.
            self._built = new_built
            self._handler = new_handler
            if self._http is not None:
                self._http.replace_handler(new_handler)
            if old_built is not None:
                try:
                    old_built.close()
                except Exception:  # pragma: no cover — best-effort
                    logger.exception("error closing previous runtime during reload")
            logger.info("OpenCOAT daemon reloaded (llm=%s)", new_built.llm_label)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until :meth:`stop` is called (or signal received).

        Returns ``True`` if the daemon stopped, ``False`` on timeout.
        """
        return self._stop_event.wait(timeout=timeout)

    def run_until_signal(
        self,
        *,
        signals: tuple[int, ...] = (signal.SIGTERM, signal.SIGINT),
    ) -> None:
        """Install signal handlers, :meth:`start`, block, :meth:`stop`.

        Must be called from the main thread (Python's :mod:`signal`
        only installs handlers there).
        """
        if not self._started:
            self.start()

        def _handle(signum: int, _frame: Any) -> None:
            logger.info("received %s — initiating drain", signal.Signals(signum).name)
            self._stop_event.set()

        old: dict[int, Any] = {}
        for sig in signals:
            try:
                old[sig] = signal.signal(sig, _handle)
            except ValueError:
                # Not on main thread — caller is doing something exotic;
                # fall back to polling-only wait.
                old[sig] = None
        try:
            self._stop_event.wait()
        finally:
            for sig, prev in old.items():
                if prev is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        signal.signal(sig, prev)
            self.stop()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_pid_path(_config: DaemonConfig, override: str | Path | None) -> Path | None:
        """Pick a PID file location for the daemon.

        Precedence:

        1. Explicit ``pid_file=`` constructor argument (or
           ``--pid-file`` from the CLI, which forwards here).
        2. ``OPENCOAT_PID_FILE`` env var — handy for ``launchctl``
           plists / ``systemd`` units that want to pin the path
           without rewriting the daemon config.
        3. ``None`` — no PID file, original M0 behaviour. The
           ``opencoat runtime`` CLI passes its own default
           (``~/.opencoat/opencoat.pid``) so a CLI-driven daemon
           always gets a stable PID location; tests and embedded
           callers that construct ``Daemon`` directly opt out by
           passing nothing.
        """
        import os as _os

        if override is not None:
            return Path(override)
        env = _os.environ.get("OPENCOAT_PID_FILE")
        if env:
            return Path(env).expanduser()
        return None

    def _acquire_pid_file(self) -> None:
        if self._pid_file_path is None:
            return
        # ``~/.opencoat`` may not exist on a fresh install; create it
        # eagerly so the PidFile lock can land without callers having
        # to ``mkdir -p`` first. Storage backends already do this for
        # their sqlite files, but the PID file is created earlier in
        # ``start()`` than the stores are.
        with contextlib.suppress(OSError):
            self._pid_file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._pid_file = PidFile(self._pid_file_path)
            self._pid_file.acquire()
        except PidFileError:
            raise
        except OSError as exc:
            raise RuntimeError(f"failed to acquire PID file {self._pid_file_path}: {exc}") from exc

    def _http_endpoint_str(self) -> str:
        if self._http is None:
            return "disabled"
        return f"{self._http.host}:{self._http.port}{self._http.path}"

    def _heartbeat_tick(self) -> None:
        """Invoke one heartbeat on the **current** runtime (survives :meth:`reload`)."""
        built = self._built
        if built is None:
            return
        built.runtime.tick()

    def _maybe_start_scheduler(self) -> None:
        loops = self._config.runtime.loops
        if not loops.heartbeat_enabled:
            return
        if self._built is None:
            return
        self._scheduler = Scheduler(
            self._heartbeat_tick,
            heartbeat_interval_seconds=loops.heartbeat_interval_seconds,
        )
        self._scheduler.start()

    def _maybe_start_http(self) -> None:
        ipc = self._config.ipc.http
        if not getattr(ipc, "enabled", False):
            return
        host = getattr(ipc, "host", "127.0.0.1") or "127.0.0.1"
        # Port 0 means "bind an ephemeral port" (tests, multi-instance). Do not
        # use ``or 7878`` — that would treat 0 as missing and collide with a
        # real daemon on the default port.
        _port = getattr(ipc, "port", None)
        port = int(7878 if _port is None else _port)
        path = getattr(ipc, "path", "/rpc") or "/rpc"
        assert self._handler is not None
        self._http = HttpServer(self._handler, host=host, port=port, path=path)
        self._http_thread = threading.Thread(
            target=self._http.serve_forever,
            name="opencoat-http-server",
            daemon=True,
        )
        self._http_thread.start()

    def _teardown_locked(self) -> None:
        """Tear down resources. Caller holds ``_state_lock``."""
        if self._scheduler is not None:
            try:
                self._scheduler.stop()
            except Exception:  # pragma: no cover
                logger.exception("error stopping heartbeat scheduler")
            self._scheduler = None
        if self._http is not None:
            try:
                self._http.shutdown()
            except Exception:  # pragma: no cover — best-effort
                logger.exception("error shutting down HTTP server")
            try:
                self._http.server_close()
            except Exception:  # pragma: no cover
                logger.exception("error closing HTTP socket")
            if self._http_thread is not None:
                self._http_thread.join(timeout=_DRAIN_TIMEOUT_SECONDS)
            self._http = None
            self._http_thread = None
        if self._built is not None:
            try:
                self._built.close()
            except Exception:  # pragma: no cover
                logger.exception("error closing runtime")
            self._built = None
        self._handler = None
        if self._pid_file is not None:
            try:
                self._pid_file.release()
            except Exception:  # pragma: no cover
                logger.exception("error releasing PID file")
            self._pid_file = None
        self._started = False

    # ------------------------------------------------------------------
    # Context manager sugar
    # ------------------------------------------------------------------

    def __enter__(self) -> Daemon:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = ["Daemon", "DaemonAlreadyStartedError"]
