"""OpenClaw-shaped host driving :class:`OpenCOATRuntime` (M5 #32).

Run with::

    uv run python -m examples.04_openclaw_with_runtime.main

The script wires :func:`opencoat_runtime_host_openclaw.install_hooks` against
an in-memory "OpenClaw" event bus, replays a tiny lifecycle (start → user
message → memory write), prints the last :class:`ConcernInjection`, and
shows DCN activation rows for the memory concern. No network and no real
OpenClaw SDK — only the public adapter + bridge API the milestone ships.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_host_openclaw import (
    OpenClawAdapter,
    OpenClawMemoryBridge,
    install_hooks,
)
from opencoat_runtime_protocol import ConcernInjection
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

from .concerns import seed_concerns


@dataclass
class OpenClawToyHost:
    """Minimal subscribe/unsubscribe bus — satisfies :class:`OpenClawHost`."""

    _callbacks: dict[str, list[Callable[[dict[str, Any]], None]]] = field(default_factory=dict)

    def subscribe(
        self,
        event_name: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        self._callbacks.setdefault(event_name, []).append(callback)

        def _unsubscribe() -> None:
            self._callbacks[event_name].remove(callback)

        return _unsubscribe

    def fire(self, event_name: str, payload: dict[str, Any]) -> None:
        for cb in list(self._callbacks.get(event_name, [])):
            cb(payload)


@dataclass(frozen=True)
class OpenClawDemoReport:
    """Structured outcome of :func:`run_demo` for tests and CLI."""

    last_injection: ConcernInjection | None
    memory_activation_count: int
    subscription_count_after_uninstall: int
    memory_bridge_logged_demo_key: bool


def _build_runtime() -> OpenCOATRuntime:
    return OpenCOATRuntime(
        RuntimeConfig(),
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )


def _seed_stores(runtime: OpenCOATRuntime) -> None:
    for concern in seed_concerns():
        runtime.concern_store.upsert(concern)
        runtime.dcn_store.add_node(concern)


def run_demo(*, session_id: str = "demo-openclaw-session") -> OpenClawDemoReport:
    """Install hooks, fire a canned event sequence, tear down, return report."""
    runtime = _build_runtime()
    _seed_stores(runtime)
    host = OpenClawToyHost()
    adapter = OpenClawAdapter()
    bridge = OpenClawMemoryBridge(dcn_store=runtime.dcn_store)

    installed = install_hooks(
        host,
        runtime=runtime,
        adapter=adapter,
        bridge=bridge,
        event_names=(
            "agent.started",
            "agent.user_message",
            "agent.memory_write",
        ),
    )
    try:
        host.fire("agent.started", {"agent_session_id": session_id, "host_round_id": "t-0"})
        host.fire(
            "agent.user_message",
            {
                "agent_session_id": session_id,
                "host_round_id": "t-1",
                "payload": {"text": "What is the OpenCOAT runtime?"},
            },
        )
        host.fire(
            "agent.memory_write",
            {
                "agent_session_id": session_id,
                "host_round_id": "t-2",
                "payload": {
                    "key": "episodic.openclaw-demo",
                    "value": {"note": "user asked about OpenCOAT"},
                    "concern_id": "c-openclaw-memory",
                },
            },
        )
    finally:
        installed.uninstall()

    last = runtime.last_injection()
    mem_log = list(runtime.dcn_store.activation_log(concern_id="c-openclaw-memory"))
    bridge_hit = any(r.get("joinpoint_id") == "episodic.openclaw-demo" for r in mem_log)
    subs_left = sum(len(cbs) for cbs in host._callbacks.values())
    return OpenClawDemoReport(
        last_injection=last,
        memory_activation_count=len(mem_log),
        subscription_count_after_uninstall=subs_left,
        memory_bridge_logged_demo_key=bridge_hit,
    )


def _format_report(report: OpenClawDemoReport) -> str:
    lines = [
        "── OpenClaw + OpenCOAT demo ─────────────────────────────────────────",
        f"memory activations (c-openclaw-memory): {report.memory_activation_count}",
        "  (includes turn-loop logging plus the memory-bridge mirror when",
        "   ``concern_id`` is set on ``agent.memory_write``.)",
        f"bridge mirrored key 'episodic.openclaw-demo': {report.memory_bridge_logged_demo_key}",
        f"callbacks left after uninstall: {report.subscription_count_after_uninstall}",
    ]
    inj = report.last_injection
    if inj is None or not inj.injections:
        lines.append("last injection: <none>")
    else:
        lines.append(f"last injection weave_id={inj.weave_id!r} rows={len(inj.injections)}")
        for row in inj.injections:
            lines.append(f"  • target={row.target!r} mode={row.mode!r}")
            lines.append(f"      {row.content}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Exit without printing the report (smoke tests).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_demo()
    if not args.quiet:
        print(_format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
