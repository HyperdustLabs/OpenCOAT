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

            vector = self._coordinator.coordinate(
                weave_id=weave_id,
                host_round_id=joinpoint.host_round_id,
                candidates=candidates,
                joinpoint=joinpoint,
                context=ctx,
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
            if concern.pointcut is None:
                continue
            try:
                result = self._matcher.match(concern.pointcut, joinpoint, context)
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
    ) -> None:
        if not injection.injections:
            return

        scores = {a.concern_id: a.activation_score for a in vector.active_concerns}
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
                    joinpoint_id=joinpoint.id,
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
