"""Meta concern: lifecycle policy (decay rates, archive cutoffs, …)."""

from __future__ import annotations

from opencoat_runtime_protocol import Concern, LifecycleState


class LifecycleControl:
    def should_archive(self, concern: Concern) -> bool:
        raise NotImplementedError

    def should_weaken(self, concern: Concern) -> bool:
        raise NotImplementedError

    def decay_step(self, concern: Concern) -> float:
        raise NotImplementedError


class DefaultLifecycleControl(LifecycleControl):
    """Baseline heartbeat decay policy for M6.

    Concerns that are not reinforced accumulate ``activation_state.decay`` each
    tick. High decay triggers :meth:`~ConcernLifecycleManager.weaken`; very high
    decay triggers :meth:`~ConcernLifecycleManager.archive`.
    """

    def __init__(
        self,
        *,
        decay_step: float = 0.05,
        weaken_threshold: float = 0.5,
        archive_threshold: float = 1.0,
    ) -> None:
        if decay_step <= 0:
            raise ValueError("decay_step must be positive")
        self._decay_step = decay_step
        self._weaken_threshold = weaken_threshold
        self._archive_threshold = archive_threshold

    def decay_step(self, concern: Concern) -> float:
        state = (concern.lifecycle_state or LifecycleState.CREATED.value).lower()
        if state in {LifecycleState.ARCHIVED.value, LifecycleState.DELETED.value, LifecycleState.FROZEN.value}:
            return 0.0
        return self._decay_step

    def should_archive(self, concern: Concern) -> bool:
        activation = concern.activation_state
        if activation is None:
            return False
        return activation.decay >= self._archive_threshold

    def should_weaken(self, concern: Concern) -> bool:
        activation = concern.activation_state
        if activation is None:
            return False
        if activation.decay < self._weaken_threshold:
            return False
        return activation.decay < self._archive_threshold


__all__ = ["DefaultLifecycleControl", "LifecycleControl"]
