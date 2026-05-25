"""Concern Builder — v0.1 §20.3.

Normalizes candidate Concerns from :class:`ConcernExtractor` into activatable
concerns (pointcut + advice + weaving) and upserts them through the store.

MVP behaviour
-------------
* **Fill gaps only** — never overwrites an existing ``pointcut``, ``advice``,
  or ``weaving_policy`` on the candidate.
* **Store merge** — on upsert, preserves pointcut/advice/weaving already saved
  for the same ``id`` (so manual edits survive re-extract).
* **Templates** — ``generated_type`` / tags / ``source.origin`` drive defaults
  (see :mod:`.builder_templates`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from opencoat_runtime_protocol import (
    Advice,
    AdviceType,
    Concern,
    LifecycleState,
    Pointcut,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import ConcernScope, PointcutMatch

from ..ports import ConcernStore
from ..weaving._defaults import DEFAULT_LEVEL, DEFAULT_MODE, DEFAULT_TARGET
from .builder_templates import activation_keywords, resolve_activation


class ConcernBuilder:
    def __init__(self, *, store: ConcernStore | None = None) -> None:
        self._store = store

    @staticmethod
    def new_id() -> str:
        return f"c-{uuid4().hex[:12]}"

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    def enrich(self, candidate: Concern) -> Concern:
        """Attach pointcut / advice / weaving when missing (pure, no I/O)."""
        if (
            candidate.pointcut is not None
            and candidate.advice is not None
            and candidate.weaving_policy is not None
        ):
            return candidate

        resolved = resolve_activation(candidate)
        updates: dict[str, Any] = {}

        if candidate.pointcut is None:
            keywords = activation_keywords(candidate)
            updates["pointcut"] = Pointcut(
                joinpoints=list(resolved.joinpoints),
                match=PointcutMatch(any_keywords=keywords) if keywords else None,
            )
        elif (
            candidate.pointcut.match is None
            and not candidate.pointcut.context_predicates
            and not candidate.pointcut.joinpoints
        ):
            keywords = activation_keywords(candidate)
            updates["pointcut"] = candidate.pointcut.model_copy(
                update={
                    "joinpoints": list(resolved.joinpoints),
                    "match": PointcutMatch(any_keywords=keywords) if keywords else None,
                }
            )
        elif candidate.pointcut.joinpoints == [] and resolved.joinpoints:
            updates["pointcut"] = candidate.pointcut.model_copy(
                update={"joinpoints": list(resolved.joinpoints)}
            )

        advice_type = resolved.advice_type
        if candidate.advice is None:
            updates["advice"] = _default_advice(candidate, advice_type)
        else:
            advice_type = AdviceType(candidate.advice.type)

        if candidate.weaving_policy is None:
            updates["weaving_policy"] = WeavingPolicy(
                mode=DEFAULT_MODE[advice_type],
                level=DEFAULT_LEVEL[advice_type],
                target=DEFAULT_TARGET[advice_type],
                priority=resolved.priority,
            )

        if candidate.scope is None:
            duration = "session" if _long_lived(candidate) else "turn"
            pc = updates.get("pointcut") or candidate.pointcut
            raw_jps = pc.joinpoints if pc is not None else list(resolved.joinpoints)
            coverage = [jp for jp in raw_jps if isinstance(jp, str)]
            updates["scope"] = ConcernScope(
                duration=duration,
                joinpoint_coverage=coverage,
            )

        if candidate.lifecycle_state == LifecycleState.CREATED:
            updates["lifecycle_state"] = LifecycleState.ACTIVE

        if not updates:
            return candidate
        return candidate.model_copy(update=updates)

    def build_or_update(self, candidate: Concern) -> Concern:
        """Normalize a candidate Concern and upsert it into the store."""
        if self._store is None:
            raise RuntimeError("ConcernBuilder.build_or_update requires a ConcernStore")
        enriched = self.enrich(candidate)
        existing = self._store.get(enriched.id)
        if existing is not None:
            enriched = _merge_preserve_customizations(existing, enriched)
        now = self.now()
        if enriched.created_at is None:
            enriched = enriched.model_copy(update={"created_at": now})
        enriched = enriched.model_copy(update={"updated_at": now})
        return self._store.upsert(enriched)

    def build_many(self, candidates: list[Concern]) -> list[Concern]:
        if self._store is None:
            raise RuntimeError("ConcernBuilder.build_many requires a ConcernStore")
        return [self.build_or_update(c) for c in candidates]


def _default_advice(concern: Concern, advice_type: AdviceType) -> Advice:
    content = (concern.description or "").strip() or concern.name
    params: dict[str, Any] | None = None
    if advice_type == AdviceType.VERIFICATION_RULE:
        keywords = activation_keywords(concern, limit=4)
        params = {"must_contain": keywords[0]} if keywords else {"must_contain": concern.name[:80]}
    return Advice(type=advice_type, content=content, params=params)


def _long_lived(concern: Concern) -> bool:
    gtype = (concern.generated_type or "").lower()
    if any(x in gtype for x in ("policy", "persona", "governance", "safety")):
        return True
    origin = concern.source.origin if concern.source else ""
    return origin in ("manual_import", "host_explicit_plan", "intent_alignment", "system_default")


def _merge_preserve_customizations(existing: Concern, enriched: Concern) -> Concern:
    """Keep store customizations; take fresh extract fields for name/description/tags."""
    merged = enriched.model_copy(
        update={
            "metrics": existing.metrics,
            "activation_state": existing.activation_state,
            "relations": existing.relations,
        }
    )
    if existing.created_at is not None:
        merged = merged.model_copy(update={"created_at": existing.created_at})
    if existing.pointcut is not None:
        merged = merged.model_copy(update={"pointcut": existing.pointcut})
    if existing.advice is not None:
        merged = merged.model_copy(update={"advice": existing.advice})
    if existing.weaving_policy is not None:
        merged = merged.model_copy(update={"weaving_policy": existing.weaving_policy})
    if existing.scope is not None:
        merged = merged.model_copy(update={"scope": existing.scope})
    # Do not regress lifecycle on re-extract.
    if existing.lifecycle_state not in (
        LifecycleState.CREATED,
        LifecycleState.DELETED,
    ):
        merged = merged.model_copy(update={"lifecycle_state": existing.lifecycle_state})
    return merged


__all__ = ["ConcernBuilder"]
