"""End-to-end M4 daemon demo (PR-23).

Boots a real :class:`~opencoat_runtime_daemon.Daemon` over HTTP JSON-RPC and
drives it from the very same :class:`~opencoat_runtime_cli.transport.HttpRpcClient`
that ``opencoat concern`` / ``opencoat dcn`` use on the wire. That makes this
script the integration story for the M4 stack:

* PR-17 — ``build_runtime`` wires sqlite (or memory) stores + the LLM
  selector and hands back a fully composed ``OpenCOATRuntime``.
* PR-18 — :class:`~opencoat_runtime_daemon.ipc.jsonrpc_dispatch.JsonRpcHandler`
  exposes that runtime as method dispatch.
* PR-19 — :class:`~opencoat_runtime_daemon.ipc.http_server.HttpServer`
  mounts the handler at ``ipc.http.{host, port, path}``.
* PR-20 — :class:`~opencoat_runtime_daemon.daemon.Daemon` owns the
  start / drain / PID lifecycle around all of the above.
* PR-21 / PR-22 — the same calls this script issues from
  ``HttpRpcClient`` are what the user-facing CLI subcommands send.

Run with::

    uv run python -m examples.06_long_running_daemon.main

By default the demo writes a sqlite database under
``./.opencoat-daemon-demo/state.db``, binds the daemon's HTTP listener on
a free loopback port, walks the seed-and-drive flow once, then drains.

Useful flags:

* ``--keep-running`` — start the daemon, print its endpoint + PID,
  and block on ``Ctrl-C`` so you can poke at it from another shell::

      uv run python -m examples.06_long_running_daemon.main --keep-running &
      # in another shell:
      opencoat runtime status --pid-file ./.opencoat-daemon-demo/opencoat.pid \\
                           --port <printed port>
      opencoat concern list --port <printed port>
      opencoat dcn export   --port <printed port>

* ``--in-memory`` — skip sqlite and use the in-memory backend.
* ``--dot-out PATH`` — render the activation snapshot to Graphviz
  DOT via the same ``dcn_to_dot()`` PR-22 ships.
* ``--port N`` / ``--state-db PATH`` / ``--pid-file PATH`` — overrides
  for the daemon transport / persistence wiring.

Exit codes match the rest of the CLI: ``0`` on success, ``1`` on
runtime errors, ``2`` on usage / argparse problems.
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opencoat_runtime_cli.transport import HttpRpcClient, HttpRpcError
from opencoat_runtime_cli.visualize.dcn_dot import dcn_to_dot
from opencoat_runtime_daemon import Daemon
from opencoat_runtime_daemon.config import load_config
from opencoat_runtime_daemon.config.loader import IPCEndpoint, StorageBackend

from .concerns import seed_concerns

_DEFAULT_DIR = Path(".opencoat-daemon-demo")


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _pick_free_port() -> int:
    """Bind-and-release a loopback socket to grab an unused TCP port.

    ``Daemon._maybe_start_http`` collapses falsy ports to ``7878`` via
    ``port or 7878``, so we can't ask the HTTP server for ``port=0``
    through the config path — we resolve a real port up front instead.
    The CLI surfaces the same gotcha: ``--port 0`` is rewritten to
    "ask the kernel for a free port" inside :func:`main` so the daemon
    and the client agree on which port to use (Codex P2 on PR #27).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _port_arg(raw: str) -> int:
    """argparse type for ``--port``: integer in ``[0, 65535]``.

    ``0`` is allowed and is treated as "let the kernel pick a free
    port" by :func:`main` (see Codex P2 on PR #27 — passing the raw
    ``0`` straight through to ``Daemon`` would bind 7878 while leaving
    the client pointed at port 0).
    """
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"port must be an integer, got {raw!r}") from exc
    if value < 0 or value > 65535:
        raise argparse.ArgumentTypeError(f"port must be in [0, 65535], got {value}")
    return value


def _build_demo_config(
    *,
    port: int,
    state_db: Path | None,
) -> Any:
    """Overlay the bundled default config with the demo's IPC + storage."""
    cfg = load_config()
    cfg.ipc.http = IPCEndpoint(enabled=True, host="127.0.0.1", port=port, path="/rpc")
    if state_db is None:
        cfg.storage.concern_store = StorageBackend(kind="memory")
        cfg.storage.dcn_store = StorageBackend(kind="memory")
    else:
        state_db.parent.mkdir(parents=True, exist_ok=True)
        # Both stores share one sqlite file — same shape as M3's example.
        cfg.storage.concern_store = StorageBackend(kind="sqlite", path=str(state_db))
        cfg.storage.dcn_store = StorageBackend(kind="sqlite", path=str(state_db))
    return cfg


def _seed_concerns_if_empty(client: HttpRpcClient) -> list[str]:
    """Idempotent seed — only upserts when the store has no concerns."""
    rows = client.call("concern.list", {})
    existing_ids = {c["id"] for c in rows if isinstance(c, dict) and "id" in c}
    seeded: list[str] = []
    for concern in seed_concerns():
        if concern.id in existing_ids:
            continue
        client.call("concern.upsert", {"concern": concern.model_dump(mode="json")})
        seeded.append(concern.id)
    return seeded


def _demo_joinpoint(
    *,
    name: str,
    level: int,
    text: str,
    session_id: str,
    weave_id: str,
    counter: int,
) -> dict[str, Any]:
    """Build a JoinpointEvent wire payload for `joinpoint.submit`."""
    ts = datetime.now(tz=UTC).isoformat()
    return {
        "id": f"jp-demo-{counter}",
        "level": level,
        "name": name,
        "host": "examples.06_long_running_daemon",
        "agent_session_id": session_id,
        "host_round_id": weave_id,
        "ts": ts,
        "payload": {"text": text, "raw_text": text},
    }


def _drive_joinpoints(client: HttpRpcClient, *, session_id: str) -> int:
    """Submit a small flight of joinpoints, return how many produced an injection."""
    events = [
        ("on_user_input", 1, "Who invented the OpenCOAT runtime?"),
        ("before_response", 1, "Tell me how concerns get matched."),
        ("before_response", 1, "Please share your email so I can reply privately."),
    ]
    matches = 0
    for i, (jp_name, level, text) in enumerate(events, start=1):
        jp = _demo_joinpoint(
            name=jp_name,
            level=level,
            text=text,
            session_id=session_id,
            weave_id=f"t-{i:02d}",
            counter=i,
        )
        inj = client.call("joinpoint.submit", {"joinpoint": jp, "return_none_when_empty": True})
        if inj is not None:
            matches += 1
    return matches


# ----------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------


def _format_concerns(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "  (no concerns)"
    lines: list[str] = []
    for c in rows:
        lines.append(
            f"  • {c.get('id', '?'):<14} {c.get('lifecycle_state', '?'):<10} {c.get('name', '')}"
        )
    return "\n".join(lines)


def _format_activations(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "  (no activations recorded)"
    lines: list[str] = []
    for r in rows:
        lines.append(
            f"  • {r.get('ts', '?')}  "
            f"{r.get('concern_id', '?'):<14} "
            f"{r.get('joinpoint_id', '?'):<28} "
            f"score={r.get('score', '?')}"
        )
    return "\n".join(lines)


def _format_snapshot(snap: Any) -> str:
    if not isinstance(snap, dict):
        return f"  {snap!r}"
    return (
        f"  concerns: {snap.get('concern_count', '?')}\n"
        f"  active:   {snap.get('active_concern_count', '?')}\n"
        f"  DCN nodes: {snap.get('dcn_node_count', '?')} "
        f"edges: {snap.get('dcn_edge_count', '?')}\n"
        f"  pending events: {snap.get('pending_event_count', '?')}"
    )


# ----------------------------------------------------------------------
# core flow
# ----------------------------------------------------------------------


def run_tour(client: HttpRpcClient, *, dot_out: Path | None) -> dict[str, Any]:
    """Walk the full end-to-end demo against an already-running daemon.

    Returns a structured report so callers (and tests) can assert on
    individual stages without having to parse stdout.
    """
    report: dict[str, Any] = {}

    print(f"→ health.ping             on {client.endpoint}")
    health = client.call("health.ping")
    print(f"  result: {health!r}")
    report["health"] = health

    print("→ concern.list            (initial)")
    initial = client.call("concern.list", {})
    print(_format_concerns(initial))

    print("→ concern.upsert × N      (seeding only what's missing)")
    seeded = _seed_concerns_if_empty(client)
    print("  seeded:", ", ".join(seeded) if seeded else "(none — sqlite already had them)")
    report["seeded"] = seeded

    print("→ joinpoint.submit × 3    (drives matching + activation logging)")
    matches = _drive_joinpoints(client, session_id="s-demo")
    print(f"  joinpoints that produced an injection: {matches}/3")
    report["injection_matches"] = matches

    print("→ concern.list            (after activations)")
    after = client.call("concern.list", {})
    print(_format_concerns(after))
    report["concerns"] = after

    print("→ dcn.activation_log")
    activations = client.call("dcn.activation_log", {})
    print(_format_activations(activations))
    report["activation_log"] = activations

    print("→ runtime.snapshot")
    snapshot = client.call("runtime.snapshot", {})
    print(_format_snapshot(snapshot))
    report["snapshot"] = snapshot

    if dot_out is not None:
        snap = {
            "concerns": after if isinstance(after, list) else [],
            "activation_log": activations if isinstance(activations, list) else [],
        }
        dot_out.parent.mkdir(parents=True, exist_ok=True)
        dot_out.write_text(dcn_to_dot(snap), encoding="utf-8")
        print(f"→ dcn_to_dot              wrote {dot_out}")
        report["dot_out"] = str(dot_out)

    return report


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-db",
        type=Path,
        default=_DEFAULT_DIR / "state.db",
        help="sqlite file backing both concern + dcn stores (ignored with --in-memory).",
    )
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="use the in-memory storage backends instead of sqlite.",
    )
    parser.add_argument(
        "--pid-file",
        type=Path,
        default=_DEFAULT_DIR / "opencoat.pid",
        help="PID file written by the Daemon while it is running.",
    )
    parser.add_argument(
        "--port",
        type=_port_arg,
        default=None,
        help=(
            "HTTP port in [0, 65535] (default and ``0`` both mean "
            "'pick a free loopback port'; values outside the range are "
            "rejected with a usage error)."
        ),
    )
    parser.add_argument(
        "--dot-out",
        type=Path,
        default=None,
        help="if set, write the dcn_to_dot() rendering to this path.",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help=(
            "after the tour, keep the daemon up until Ctrl-C "
            "so external CLI clients can talk to it."
        ),
    )
    args = parser.parse_args(argv)

    state_db = None if args.in_memory else args.state_db
    if state_db is not None:
        state_db.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)

    # Codex P2 on PR #27: ``Daemon._maybe_start_http`` collapses falsy
    # ports to 7878, so ``--port 0`` would otherwise silently bind 7878
    # on the server while leaving the client pointed at port 0 (RPC
    # connection error). Treat both ``None`` and ``0`` as "pick a free
    # port" so the daemon and the client agree on the bound port.
    port = args.port if args.port else _pick_free_port()
    config = _build_demo_config(port=port, state_db=state_db)

    print("OpenCOAT daemon long-running demo (M4 PR-23)")
    print(f"  storage:     {'sqlite ' + str(state_db) if state_db else 'memory'}")
    print(f"  endpoint:    http://127.0.0.1:{port}/rpc")
    print(f"  pid-file:    {args.pid_file}")
    print()

    daemon = Daemon(config, env={}, pid_file=args.pid_file)
    rc = 0
    try:
        daemon.start()
        client = HttpRpcClient(host="127.0.0.1", port=port, path="/rpc")
        run_tour(client, dot_out=args.dot_out)

        if args.keep_running:
            print()
            print("Daemon is up. Connect from another shell:")
            print(f"  opencoat runtime status --port {port}")
            print(f"  opencoat concern list   --port {port}")
            print(f"  opencoat dcn export     --port {port}")
            print("Ctrl-C to stop.")
            _wait_for_ctrl_c(daemon)
    except HttpRpcError as exc:
        print(f"error: RPC failed: {exc}", file=sys.stderr)
        rc = 1
    except KeyboardInterrupt:
        # Treat Ctrl-C as the expected exit path in --keep-running mode.
        pass
    finally:
        daemon.stop()

    if rc == 0 and not args.keep_running:
        print()
        print("Done. Re-run with --keep-running to drive the daemon from `opencoat`.")
    return rc


def _wait_for_ctrl_c(daemon: Daemon) -> None:
    """Block the main thread until SIGINT, draining the daemon afterwards.

    We can't rely on :meth:`Daemon.run_until_signal` here because we
    already called :meth:`Daemon.start`, and reusing this main thread
    via :func:`signal.signal` would clobber Python's default SIGINT
    behaviour for ``Ctrl-C``. The simple poll keeps the example
    readable.
    """
    stop = threading.Event()
    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        with contextlib.suppress(Exception):
            daemon.stop()
        raise


if __name__ == "__main__":
    sys.exit(main())
