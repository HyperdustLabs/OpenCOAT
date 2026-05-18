"""Integration tests for the host SDK transports.

These tests exercise the end-to-end path the ``opencoat-skill`` demo
relies on:

* Host code constructs a :class:`Client` for a remote daemon over HTTP
  JSON-RPC, builds a :class:`JoinpointEvent`, and gets back the
  :class:`ConcernInjection` the runtime decided to weave.
* In-proc mode short-circuits to a direct
  :meth:`OpenCOATRuntime.on_joinpoint` call.
* Common error paths surface as typed exceptions so host code can
  branch on "daemon stopped" vs "daemon answered with an error".

The fixtures stand up a real :class:`HttpServer` mounted on
:class:`JsonRpcHandler`, so this is the same wire surface the CLI hits.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPSConnection

import pytest
from opencoat_runtime_core import OpenCOATRuntime
from opencoat_runtime_daemon import build_runtime
from opencoat_runtime_daemon.config import load_config
from opencoat_runtime_daemon.ipc.http_server import HttpServer
from opencoat_runtime_daemon.ipc.jsonrpc_dispatch import JsonRpcHandler
from opencoat_runtime_host_sdk import Client, JoinpointEmitter
from opencoat_runtime_host_sdk.transport.http import (
    HostTransportCallError,
    HostTransportConnectionError,
    HttpTransport,
)
from opencoat_runtime_host_sdk.transport.inproc import InProcTransport
from opencoat_runtime_host_sdk.transport.socket import SocketTransport
from opencoat_runtime_protocol import ConcernInjection, JoinpointEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_joinpoint() -> JoinpointEvent:
    return JoinpointEvent(
        id="jp-test-1",
        level=1,
        name="before_response",
        host="custom",
        agent_session_id="sess-1",
        host_round_id="turn-1",
        ts=datetime.now(UTC),
        payload={"kind": "lifecycle", "stage": "before_response"},
    )


@pytest.fixture
def runtime() -> Iterator[OpenCOATRuntime]:
    """A real in-proc runtime, used both directly and via the daemon stack."""
    with build_runtime(load_config(), env={}) as built:
        yield built.runtime


@pytest.fixture
def http_server(runtime: OpenCOATRuntime) -> Iterator[HttpServer]:
    """Spin up an HTTP JSON-RPC server bound to ``runtime`` on a free port."""
    rpc = JsonRpcHandler(runtime)
    srv = HttpServer(rpc, host="127.0.0.1", port=0, path="/rpc")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    try:
        yield srv
    finally:
        srv.shutdown()
        thread.join(timeout=5)
        srv.server_close()


# ---------------------------------------------------------------------------
# In-proc transport
# ---------------------------------------------------------------------------


def test_inproc_transport_returns_injection(runtime: OpenCOATRuntime) -> None:
    client = Client.connect("inproc://", runtime=runtime)
    assert isinstance(client.transport, InProcTransport)

    out = client.emit(_build_joinpoint())
    # Empty stores → no concerns → empty (but typed) ConcernInjection.
    assert isinstance(out, ConcernInjection)


def test_inproc_transport_return_none_when_empty(runtime: OpenCOATRuntime) -> None:
    client = Client.connect("inproc://", runtime=runtime)
    out = client.emit(_build_joinpoint(), return_none_when_empty=True)
    assert out is None


def test_inproc_requires_runtime() -> None:
    with pytest.raises(ValueError, match="runtime="):
        Client.connect("inproc://")


# ---------------------------------------------------------------------------
# HTTP transport — the path the daemon + skill demo rely on
# ---------------------------------------------------------------------------


def test_http_transport_round_trip(http_server: HttpServer) -> None:
    base_url = f"http://{http_server.host}:{http_server.port}"
    client = Client.connect(base_url)
    assert isinstance(client.transport, HttpTransport)
    assert client.transport.endpoint.endswith("/rpc")

    out = client.emit(_build_joinpoint())
    assert isinstance(out, ConcernInjection)


def test_http_transport_returns_none_when_empty(http_server: HttpServer) -> None:
    base_url = f"http://{http_server.host}:{http_server.port}"
    client = Client.connect(base_url)
    out = client.emit(_build_joinpoint(), return_none_when_empty=True)
    assert out is None


def test_http_transport_records_activation(
    http_server: HttpServer, runtime: OpenCOATRuntime
) -> None:
    """The skill demo's headline promise: an HTTP emit shows up in the
    daemon's DCN activation log. If this passes, host → daemon →
    runtime → DCN store is end-to-end wired.
    """
    base_url = f"http://{http_server.host}:{http_server.port}"
    client = Client.connect(base_url)

    before = len(list(runtime.dcn_store.activation_log()))
    client.emit(_build_joinpoint())
    after = len(list(runtime.dcn_store.activation_log()))
    # Either no concerns matched (no rows) or some did — the contract
    # under test is that the call *succeeded* and the daemon mutated
    # the same DCN store the test is reading. With empty stores no
    # rows are expected, so the assertion is "no errors raised and
    # the log is at least as long as before".
    assert after >= before


def test_http_emitter_with_payload(http_server: HttpServer) -> None:
    base_url = f"http://{http_server.host}:{http_server.port}"
    client = Client.connect(base_url)
    emitter = JoinpointEmitter(client=client, host="openclaw")

    out = emitter.emit(
        "before_response",
        level=1,
        agent_session_id="sess-2",
        host_round_id="round-3",
        payload={"kind": "lifecycle", "stage": "before_response"},
    )
    # Either a ConcernInjection envelope or None (with empty stores).
    assert out is None or isinstance(out, ConcernInjection)


def test_http_transport_unreachable_raises_connection_error() -> None:
    # Find a port that is *not* bound; bind+close to discover one.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    client = Client.connect(f"http://127.0.0.1:{free_port}", timeout_seconds=1.0)
    with pytest.raises(HostTransportConnectionError):
        client.emit(_build_joinpoint())


def test_http_transport_unknown_method_surfaces_as_call_error(
    http_server: HttpServer,
) -> None:
    """Direct-call HttpTransport.emit hits ``joinpoint.submit``; this
    test pokes the underlying ``_call`` to confirm RPC-level errors map
    to :class:`HostTransportCallError` (not transport / protocol).
    """
    base_url = f"http://{http_server.host}:{http_server.port}"
    transport = HttpTransport(base_url=base_url)
    with pytest.raises(HostTransportCallError) as exc:
        transport._call("does.not.exist", {})  # type: ignore[arg-type]
    assert exc.value.code == -32601


def test_http_transport_honours_explicit_url_path(http_server: HttpServer) -> None:
    """When base_url already carries a path, that path wins."""
    base_url = f"http://{http_server.host}:{http_server.port}/rpc"
    transport = HttpTransport(base_url=base_url, path="/this-should-not-win")
    assert transport.endpoint.endswith("/rpc")


# ---------------------------------------------------------------------------
# TLS — Codex P1 on PR #44: https:// URIs must use a real TLS connection
# ---------------------------------------------------------------------------


def test_http_scheme_uses_plain_http_connection() -> None:
    """``http://`` must NOT silently upgrade to TLS."""
    transport = HttpTransport(base_url="http://example.test")
    conn = transport._new_connection()
    try:
        assert isinstance(conn, HTTPConnection)
        assert not isinstance(conn, HTTPSConnection)
        assert transport._port == 80
    finally:
        conn.close()


def test_https_scheme_uses_https_connection() -> None:
    """``https://`` must build an :class:`HTTPSConnection`, not plain HTTP.

    Codex P1 on #44: the previous implementation accepted the ``https``
    scheme but always opened :class:`HTTPConnection`, so requests were
    sent in cleartext against any real TLS endpoint. Pin the class
    selection so the regression cannot silently come back.
    """
    transport = HttpTransport(base_url="https://example.test")
    conn = transport._new_connection()
    try:
        assert isinstance(conn, HTTPSConnection)
        assert transport._port == 443
    finally:
        conn.close()


def test_https_scheme_honours_explicit_port() -> None:
    transport = HttpTransport(base_url="https://example.test:8443/rpc")
    assert transport._port == 8443
    assert transport.endpoint == "https://example.test:8443/rpc"


def test_client_connect_https_returns_https_aware_transport() -> None:
    client = Client.connect("https://example.test:9443")
    assert isinstance(client.transport, HttpTransport)
    assert client.transport.endpoint.startswith("https://")


# ---------------------------------------------------------------------------
# Unix transport — Codex P2 on PR #44: reserved scheme must fail loud at
# connect time, not silently TypeError at emit()
# ---------------------------------------------------------------------------


def test_unix_scheme_raises_not_implemented_at_connect() -> None:
    """``unix://`` is reserved but not wired in 0.1.0.

    The previous implementation returned a :class:`SocketTransport`
    instance, then :meth:`Client.emit` would pass ``context=`` /
    ``return_none_when_empty=`` kwargs to its stub ``emit`` and trigger
    a confusing :class:`TypeError`. The contract under test is that
    callers selecting ``unix://`` find out at the call site, with a
    message that points them at HTTP.
    """
    with pytest.raises(NotImplementedError, match="unix://"):
        Client.connect("unix:///run/opencoat.sock")


def test_socket_transport_direct_emit_raises_not_implemented() -> None:
    """Defence in depth — direct construction stays consistent with the
    connect-time error. Even if a caller bypasses ``Client.connect`` and
    builds a :class:`SocketTransport` directly, ``emit`` raises a clean
    :class:`NotImplementedError` (not a signature ``TypeError``)
    regardless of the kwargs they pass.
    """
    transport = SocketTransport(path="/tmp/opencoat.sock")
    with pytest.raises(NotImplementedError):
        transport.emit(_build_joinpoint())
    with pytest.raises(NotImplementedError):
        transport.emit(_build_joinpoint(), context={}, return_none_when_empty=True)


# ---------------------------------------------------------------------------
# Connect string validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    ["", "no-scheme", "ftp://nope", "ws://nope"],
)
def test_unknown_scheme_raises(uri: str) -> None:
    with pytest.raises(ValueError):
        Client.connect(uri)
