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
from .joinpoint.discovery import JoinpointDiscovery
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
from .weaving.merge import merge_injections

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
        auto = self._config.joinpoint_automation
        self._joinpoint_discovery = JoinpointDiscovery(automation=auto)

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
        if self._should_expand_prompt_surface(jp):
            return self._run_joinpoint_surface(
                jp,
                context=context,
                return_none_when_empty=return_none_when_empty,
            )
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
        """Heartbeat-loop: maintenance, optional event weave, and ``runtime_tick``."""
        report = self._heartbeat_loop.tick(now)
        auto = self._config.joinpoint_automation
        # Drain queued host events before ``runtime_tick`` so an empty tick weave
        # does not clear a successful event injection (``return_none_when_empty``).
        if auto.process_events_on_tick:
            for event in self.drain_events():
                self._weave_runtime_event(event)
        if auto.weave_on_tick:
            tick_jp = self._joinpoint_discovery.runtime_tick_joinpoint(report)
            self._joinpoint_pipeline.run(
                tick_jp,
                return_none_when_empty=True,
                preserve_last_on_empty=True,
            )
        return report

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

    def _should_expand_prompt_surface(self, jp: JoinpointEvent) -> bool:
        auto = self._config.joinpoint_automation
        if not auto.expand_prompt_surface:
            return False
        payload = jp.payload or {}
        if payload.get("expand") is False:
            return False
        if payload.get("expand") is True:
            return True
        return "messages" in payload or "copr" in payload

    def _run_joinpoint_surface(
        self,
        root: JoinpointEvent,
        *,
        context: dict[str, Any] | None,
        return_none_when_empty: bool,
    ) -> ConcernInjection | None:
        joinpoints = self._joinpoint_discovery.expand(root)
        auto = self._config.joinpoint_automation
        if auto.batch_surface_weave:
            injection = self._joinpoint_pipeline.run_surface(
                root,
                joinpoints,
                context=context,
                return_none_when_empty=return_none_when_empty,
            )
        else:
            batch_weave_id = f"weave-{root.id}"
            merged: ConcernInjection | None = None
            for child in joinpoints:
                inj = self._joinpoint_pipeline.run(
                    child,
                    context=context,
                    return_none_when_empty=True,
                )
                merged = merge_injections(
                    merged,
                    inj,
                    weave_id=batch_weave_id,
                    host_round_id=root.host_round_id,
                )
            injection = merged

        if injection is not None and auto.emit_adviceexecution and injection.injections:
            active_ids = [row.concern_id for row in injection.injections]
            ae_jp = self._joinpoint_discovery.adviceexecution_joinpoint(
                root,
                active_concern_ids=active_ids,
            )
            ae_inj = self._joinpoint_pipeline.run(
                ae_jp,
                context=context,
                return_none_when_empty=True,
                preserve_last_on_empty=True,
            )
            injection = merge_injections(
                injection,
                ae_inj,
                weave_id=f"weave-{root.id}",
                host_round_id=root.host_round_id,
            )

        if injection is None and return_none_when_empty:
            return None
        return injection

    def _weave_runtime_event(self, event: dict[str, Any]) -> None:
        jp = self._joinpoint_discovery.joinpoint_from_event(event)
        if jp is None:
            return
        self.on_joinpoint(jp, return_none_when_empty=True)

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
