"""Meta concern: drives long-term DCN evolution decisions."""

from __future__ import annotations

from opencoat_runtime_protocol import Concern, ConcernKind


class EvolutionControl:
    def trigger_review(self) -> bool:
        raise NotImplementedError


class DefaultEvolutionControl(EvolutionControl):
    """Run meta review when at least one meta concern is active in the store."""

    def __init__(self, *, meta_concerns: list[Concern]) -> None:
        self._meta = [
            c
            for c in meta_concerns
            if (c.kind or ConcernKind.CONCERN.value) == ConcernKind.META_CONCERN.value
            and (c.lifecycle_state or "").lower() not in ("archived", "deleted")
        ]

    def trigger_review(self) -> bool:
        return len(self._meta) > 0

    @property
    def meta_concern_count(self) -> int:
        return len(self._meta)


__all__ = ["DefaultEvolutionControl", "EvolutionControl"]
