"""Joinpoint pipeline — synchronous weave for one :class:`JoinpointEvent`.

Sequence (v0.1 §22.1):

    joinpoint event
        → candidate scan       (matcher per concern in the store)
        → coordinate           (rank · resolve · budget · top-K)
        → advice generate      (one Advice per active concern)
        → weave                (build ConcernInjection)
        → log activations      (telemetry into the DCN)
        → emit observer events
        → return injection

Design notes
------------
* The pipeline is **stateless across weave runs** — cross-round memory lives
  in the stores.
* ``weave_id`` identifies one joinpoint weave (``weave-{joinpoint.id}``).
  ``host_round_id`` on the joinpoint is the host agent's dialog round
  (e.g. OpenClaw ``runId``) and must not be confused with ``weave_id``.
* Context passed to collaborators is ``payload ∪ extra`` with runtime keys
  ``weave_id`` / ``host_round_id`` assigned after the merge so payloads
  cannot shadow them.
"""

from __future__ import annotations

from typing import Any

from opencoat_runtime_protocol import (
    Advice,
    Concern,
    ConcernInjection,
    ConcernVector,
    JoinpointEvent,
)

from ..concern.executable import has_executable_pointcut, primary_pointcut
from ..config import RuntimeConfig
from ..coordinator import ConcernCoordinator
from ..ports import (
    AdvicePlugin,
    ConcernStore,
    DCNStore,
    MatcherPlugin,
    Observer,
)
from ..ports.observer import NullObserver
from ..weaving import ConcernWeaver


class JoinpointPipeline:
    """Drive a single joinpoint through the full match → weave pipeline."""

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        matcher: MatcherPlugin,
        coordinator: ConcernCoordinator,
        weaver: ConcernWeaver,
        advice_plugin: AdvicePlugin,
        observer: Observer | None = None,
    ) -> None:
        self._config = config
        self._concern_store = concern_store
        self._dcn_store = dcn_store
        self._matcher = matcher
        self._coordinator = coordinator
        self._weaver = weaver
        self._advice_plugin = advice_plugin
        self._observer = observer or NullObserver()
        self._last_vector: ConcernVector | None = None
        self._last_injection: ConcernInjection | None = None

    def run(
        self,
        joinpoint: JoinpointEvent,
        *,
        context: dict[str, Any] | None = None,
        return_none_when_empty: bool = False,
        preserve_last_on_empty: bool = False,
    ) -> ConcernInjection | None:
        weave_id = self._mint_weave_id(joinpoint)
        ctx = self._build_context(
            joinpoint,
            context,
            weave_id=weave_id,
            host_round_id=joinpoint.host_round_id,
        )

        with self._observer.on_span(
            "opencoat.weave",
            weave_id=weave_id,
            host_round_id=joinpoint.host_round_id or "",
            joinpoint=joinpoint.name,
        ):
            candidates = list(self._scan_candidates(joinpoint, ctx))
            self._observer.on_metric(
                "opencoat.weave.candidates",
                float(len(candidates)),
                joinpoint=joinpoint.name,
            )

            if not candidates and return_none_when_empty:
                if not preserve_last_on_empty:
                    self._last_vector = None
                    self._last_injection = None
                return None

            catalog = list(self._concern_store.iter_all())
            vector = self._coordinator.coordinate(
                weave_id=weave_id,
                host_round_id=joinpoint.host_round_id,
                candidates=candidates,
                joinpoint=joinpoint,
                context=ctx,
                concern_catalog=catalog,
            )
            self._last_vector = vector

            advices = self._generate_advices(vector, ctx)
            concerns = {c.id: c for c, _ in candidates}
            injection = self._weaver.build(
                weave_id=weave_id,
                host_round_id=joinpoint.host_round_id,
                vector=vector,
                concerns=concerns,
                advices=advices,
            )
            self._last_injection = injection

            self._record_activations(joinpoint, vector, injection)
            self._emit_telemetry(joinpoint, vector, injection)

            return injection

    def run_surface(
        self,
        root: JoinpointEvent,
        joinpoints: list[JoinpointEvent],
        *,
        context: dict[str, Any] | None = None,
        return_none_when_empty: bool = False,
    ) -> ConcernInjection | None:
        """Batch match + single weave for an expanded prompt surface (P3)."""
        weave_id = f"weave-{root.id}"
        base_ctx = dict(context or {})

        with self._observer.on_span(
            "opencoat.weave.surface",
            weave_id=weave_id,
            host_round_id=root.host_round_id or "",
            joinpoint=root.name,
            joinpoint_count=str(len(joinpoints)),
        ):
            candidates = self._scan_candidates_surface(
                joinpoints, weave_id, root.host_round_id, base_ctx
            )
            self._observer.on_metric(
                "opencoat.weave.candidates",
                float(len(candidates)),
                joinpoint=root.name,
            )

            if not candidates and return_none_when_empty:
                self._last_vector = None
                self._last_injection = None
                return None

            ctx = self._build_context(
                root,
                base_ctx,
                weave_id=weave_id,
                host_round_id=root.host_round_id,
            )
            catalog = list(self._concern_store.iter_all())
            vector = self._coordinator.coordinate(
                weave_id=weave_id,
                host_round_id=root.host_round_id,
                candidates=candidates,
                joinpoint=root,
                context=ctx,
                concern_catalog=catalog,
            )
            self._last_vector = vector

            advices = self._generate_advices(vector, ctx)
            concerns = {c.id: c for c, _, _ in candidates}
            injection = self._weaver.build(
                weave_id=weave_id,
                host_round_id=root.host_round_id,
                vector=vector,
                concerns=concerns,
                advices=advices,
            )
            self._last_injection = injection

            activation_jps = {c.id: jp.id for c, _, jp in candidates}
            self._record_activations(
                root,
                vector,
                injection,
                activation_joinpoint_ids=activation_jps,
            )
            self._emit_telemetry(root, vector, injection)
            return injection

    @property
    def last_vector(self) -> ConcernVector | None:
        return self._last_vector

    @property
    def last_injection(self) -> ConcernInjection | None:
        return self._last_injection

    def _scan_candidates(
        self,
        joinpoint: JoinpointEvent,
        context: dict[str, Any],
    ) -> list[tuple[Concern, float]]:
        scanned: list[tuple[Concern, float]] = []
        for concern in self._concern_store.iter_all():
            if not has_executable_pointcut(concern):
                continue
            pc = primary_pointcut(concern)
            assert pc is not None
            try:
                result = self._matcher.match(pc, joinpoint, context)
            except Exception as exc:
                self._observer.on_log(
                    "warning",
                    "matcher raised; treating as miss",
                    concern_id=concern.id,
                    error=repr(exc),
                )
                continue
            if not result.matched:
                continue
            scanned.append((concern, float(result.score)))
        return scanned

    def _scan_candidates_surface(
        self,
        joinpoints: list[JoinpointEvent],
        weave_id: str,
        host_round_id: str | None,
        base_context: dict[str, Any],
    ) -> list[tuple[Concern, float, JoinpointEvent]]:
        best: dict[str, tuple[Concern, float, JoinpointEvent]] = {}
        for concern in self._concern_store.iter_all():
            if not has_executable_pointcut(concern):
                continue
            pc = primary_pointcut(concern)
            assert pc is not None
            for jp in joinpoints:
                ctx = self._build_context(
                    jp,
                    base_context,
                    weave_id=weave_id,
                    host_round_id=host_round_id,
                )
                try:
                    result = self._matcher.match(pc, jp, ctx)
                except Exception as exc:
                    self._observer.on_log(
                        "warning",
                        "matcher raised; treating as miss",
                        concern_id=concern.id,
                        error=repr(exc),
                    )
                    continue
                if not result.matched:
                    continue
                score = float(result.score)
                prev = best.get(concern.id)
                if prev is None or score > prev[1]:
                    best[concern.id] = (concern, score, jp)
        return list(best.values())

    def _generate_advices(
        self,
        vector: ConcernVector,
        context: dict[str, Any],
    ) -> dict[str, Advice]:
        advices: dict[str, Advice] = {}
        for active in vector.active_concerns:
            concern = self._concern_store.get(active.concern_id)
            if concern is None:
                self._observer.on_log(
                    "warning",
                    "active concern vanished from store between scan and weave",
                    concern_id=active.concern_id,
                )
                continue
            try:
                advices[active.concern_id] = self._advice_plugin.generate(concern, context)
            except Exception as exc:
                self._observer.on_log(
                    "error",
                    "advice plugin raised; skipping concern",
                    concern_id=active.concern_id,
                    error=repr(exc),
                )
        return advices

    def _record_activations(
        self,
        joinpoint: JoinpointEvent,
        vector: ConcernVector,
        injection: ConcernInjection,
        *,
        activation_joinpoint_ids: dict[str, str] | None = None,
    ) -> None:
        if not injection.injections:
            return

        scores = {a.concern_id: a.activation_score for a in vector.active_concerns}
        jp_ids = activation_joinpoint_ids or {}
        for cid in _unique_concern_ids(injection):
            concern = self._concern_store.get(cid)
            if concern is None:
                self._observer.on_log(
                    "warning",
                    "concern in injection vanished from store; activation skipped",
                    concern_id=cid,
                )
                continue
            try:
                self._dcn_store.add_node(concern)
            except Exception as exc:
                self._observer.on_log(
                    "warning",
                    "DCN add_node failed; skipping activation log",
                    concern_id=cid,
                    error=repr(exc),
                )
                continue
            try:
                self._dcn_store.log_activation(
                    concern_id=cid,
                    joinpoint_id=jp_ids.get(cid, joinpoint.id),
                    score=float(scores.get(cid, 0.0)),
                    ts=vector.ts,
                )
            except Exception as exc:
                self._observer.on_log(
                    "warning",
                    "DCN log_activation failed",
                    concern_id=cid,
                    error=repr(exc),
                )

    def _emit_telemetry(
        self,
        joinpoint: JoinpointEvent,
        vector: ConcernVector,
        injection: ConcernInjection,
    ) -> None:
        self._observer.on_metric(
            "opencoat.weave.active_concerns",
            float(len(vector.active_concerns)),
            joinpoint=joinpoint.name,
        )
        totals = injection.totals
        if totals is not None:
            self._observer.on_metric(
                "opencoat.weave.injection_tokens",
                float(totals.tokens),
                joinpoint=joinpoint.name,
            )
            self._observer.on_metric(
                "opencoat.weave.injection_advices",
                float(totals.advice_count),
                joinpoint=joinpoint.name,
            )
        for escalation in self._coordinator.last_escalations:
            self._observer.on_log(
                "warning",
                "concern escalation emitted",
                **{k: str(v) for k, v in escalation.items()},
            )

    @staticmethod
    def _mint_weave_id(jp: JoinpointEvent) -> str:
        return f"weave-{jp.id}"

    @staticmethod
    def _build_context(
        jp: JoinpointEvent,
        extra: dict[str, Any] | None,
        *,
        weave_id: str,
        host_round_id: str | None,
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        if jp.payload:
            ctx.update(jp.payload)
        if extra:
            ctx.update(extra)
        ctx.setdefault("joinpoint", jp.name)
        ctx.setdefault("joinpoint_id", jp.id)
        ctx["weave_id"] = weave_id
        if host_round_id is not None:
            ctx["host_round_id"] = host_round_id
        return ctx


def _unique_concern_ids(injection: ConcernInjection) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for inj in injection.injections:
        if inj.concern_id in seen_set:
            continue
        seen_set.add(inj.concern_id)
        seen.append(inj.concern_id)
    return seen


# Backward-compatible alias (deprecated — use JoinpointPipeline).
TurnLoop = JoinpointPipeline

__all__ = ["JoinpointPipeline", "TurnLoop"]
