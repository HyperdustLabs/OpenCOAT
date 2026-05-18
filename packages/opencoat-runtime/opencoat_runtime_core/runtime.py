"""Top-level facade: :class:`OpenCOATRuntime`.

The facade composes every L2 module and exposes the three loop entrypoints:

* :meth:`on_joinpoint` — joinpoint pipeline (sync, returns an injection)
* :meth:`on_event`     — event loop (sync fan-out + queue)
* :meth:`tick`         — heartbeat loop (long-term DCN maintenance)

M1 wires the in-proc happy path: in-memory stores + stub LLM + the
default matcher / coordinator / weaver. Hosts can override any
collaborator at construction time. The facade itself owns no business
logic — it just composes the L2 modules and exposes a stable surface
for hosts and the daemon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opencoat_runtime_protocol import (
    ConcernInjection,
    ConcernVector,
    JoinpointEvent,
)

from .advice import AdviceGenerator
from .config import RuntimeConfig
from .coordinator import ConcernCoordinator
from .loops import EventLoop, HeartbeatLoop, HeartbeatReport, JoinpointPipeline
from .pointcut.matcher import PointcutMatcher
from .ports import (
    AdvicePlugin,
    ConcernStore,
    DCNStore,
    Embedder,
    LLMClient,
    MatcherPlugin,
    Observer,
)
from .ports.observer import NullObserver
from .weaving import ConcernWeaver

# ---------------------------------------------------------------------------
# Reports / events at the facade boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeEvent:
    """Asynchronous, non-turn-critical signal (tool result, env event, …)."""

    type: str
    ts: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class RuntimeSnapshot:
    """A read-only snapshot for introspection / debugging."""

    ts: datetime
    concern_count: int
    active_concern_count: int
    dcn_node_count: int
    dcn_edge_count: int
    pending_event_count: int


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class OpenCOATRuntime:
    """Top-level entrypoint that wires the L2 modules together.

    The facade is intentionally thin: it owns the ports and delegates to
    the per-module classes. Hosts and the daemon both go through this
    object — there is no other supported way to drive the runtime.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        llm: LLMClient,
        embedder: Embedder | None = None,
        matcher: MatcherPlugin | None = None,
        advice_plugin: AdvicePlugin | None = None,
        observer: Observer | None = None,
        coordinator: ConcernCoordinator | None = None,
        weaver: ConcernWeaver | None = None,
    ) -> None:
        self._config = config or RuntimeConfig()
        self._concern_store = concern_store
        self._dcn_store = dcn_store
        self._llm = llm
        self._embedder = embedder
        self._observer = observer or NullObserver()

        # Default to the bundled L2 implementations when the host did not
        # wire a specific collaborator. Each can be swapped independently.
        self._matcher: MatcherPlugin = matcher or PointcutMatcher()
        self._advice_plugin: AdvicePlugin = advice_plugin or AdviceGenerator(llm=llm)
        self._coordinator = coordinator or ConcernCoordinator(budgets=self._config.budgets)
        self._weaver = weaver or ConcernWeaver(budgets=self._config.budgets)

        self._joinpoint_pipeline = JoinpointPipeline(
            config=self._config,
            concern_store=concern_store,
            dcn_store=dcn_store,
            matcher=self._matcher,
            coordinator=self._coordinator,
            weaver=self._weaver,
            advice_plugin=self._advice_plugin,
            observer=self._observer,
        )
        self._event_loop = EventLoop(observer=self._observer)
        self._heartbeat_loop = HeartbeatLoop(
            concern_store=concern_store,
            dcn_store=dcn_store,
            observer=self._observer,
        )

    # --- public API --------------------------------------------------------

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def concern_store(self) -> ConcernStore:
        return self._concern_store

    @property
    def dcn_store(self) -> DCNStore:
        return self._dcn_store

    @property
    def llm(self) -> LLMClient:
        """Read-only access to the wired LLM client.

        Exposed so the daemon's JSON-RPC dispatcher can lazily build a
        :class:`~opencoat_runtime_core.concern.ConcernExtractor` over the
        same provider the runtime is already configured with (M5 PR-48 —
        ``concern.extract`` RPC). The host should not mutate the
        returned client.
        """
        return self._llm

    def on_joinpoint(
        self,
        jp: JoinpointEvent,
        *,
        context: dict[str, Any] | None = None,
        return_none_when_empty: bool = False,
    ) -> ConcernInjection | None:
        """Joinpoint pipeline: ingest a joinpoint, return an injection (or None)."""
        return self._joinpoint_pipeline.run(
            jp,
            context=context,
            return_none_when_empty=return_none_when_empty,
        )

    def on_event(self, ev: RuntimeEvent) -> None:
        """Event-loop: enqueue a non-turn-critical event."""
        self._event_loop.dispatch({"type": ev.type, "ts": ev.ts.isoformat(), "payload": ev.payload})

    def subscribe(self, callback) -> None:  # type: ignore[no-untyped-def]
        """Register a fan-out callback for :meth:`on_event`."""
        self._event_loop.subscribe(callback)

    def drain_events(self) -> list[dict[str, Any]]:
        """Pop every queued event (FIFO) — typically called by the heartbeat."""
        return self._event_loop.drain()

    def tick(self, now: datetime | None = None) -> HeartbeatReport:
        """Heartbeat-loop: drive long-term DCN maintenance."""
        return self._heartbeat_loop.tick(now)

    def current_vector(self) -> ConcernVector | None:
        """Return the most recently-computed Concern Vector, if any."""
        return self._joinpoint_pipeline.last_vector

    def last_injection(self) -> ConcernInjection | None:
        """Return the most recently-computed Concern Injection, if any."""
        return self._joinpoint_pipeline.last_injection

    def snapshot(self) -> RuntimeSnapshot:
        """Cheap, read-only snapshot used by /healthz and the CLI."""
        concerns = sum(1 for _ in self._concern_store.iter_all())
        active = (
            len(self._joinpoint_pipeline.last_vector.active_concerns)
            if self._joinpoint_pipeline.last_vector is not None
            else 0
        )
        dcn_nodes, dcn_edges = self._dcn_inventory()
        return RuntimeSnapshot(
            ts=datetime.now(UTC),
            concern_count=concerns,
            active_concern_count=active,
            dcn_node_count=dcn_nodes,
            dcn_edge_count=dcn_edges,
            pending_event_count=self._event_loop.pending_count,
        )

    # --- internal helpers --------------------------------------------------

    def _dcn_inventory(self) -> tuple[int, int]:
        """Best-effort node / edge counts from the DCN store.

        The DCN port deliberately exposes neither ``len`` nor a
        catch-all ``iter`` — different backends count differently and we
        do not want hot-path lookups in the snapshot. The in-memory
        store exposes a ``_nodes`` / ``_edges`` pair that we can poke at
        for the M1 happy path; everything else falls back to ``0``.
        """
        nodes = getattr(self._dcn_store, "_nodes", None)
        edges = getattr(self._dcn_store, "_edges", None)
        node_count = len(nodes) if isinstance(nodes, dict) else 0
        edge_count = len(edges) if isinstance(edges, dict) else 0
        return node_count, edge_count


__all__ = ["HeartbeatReport", "OpenCOATRuntime", "RuntimeEvent", "RuntimeSnapshot"]
