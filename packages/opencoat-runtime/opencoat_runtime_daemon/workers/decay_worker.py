"""Concern-decay worker — runs on heartbeat."""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.meta.lifecycle_control import DefaultLifecycleControl, LifecycleControl
from opencoat_runtime_core.ports import ConcernStore, DCNStore
from opencoat_runtime_protocol import ActivationState, Concern, LifecycleState

from ._base import Worker

_MAINTENANCE_STATES = frozenset(
    {
        LifecycleState.CREATED.value,
        LifecycleState.ACTIVE.value,
        LifecycleState.REINFORCED.value,
        LifecycleState.WEAKENED.value,
        LifecycleState.REVIVED.value,
    }
)


class DecayWorker(Worker):
    """Bump per-concern decay and apply weaken/archive transitions."""

    def __init__(
        self,
        *,
        concern_store: ConcernStore,
        dcn_store: DCNStore,
        lifecycle: ConcernLifecycleManager | None = None,
        policy: LifecycleControl | None = None,
    ) -> None:
        self._concern_store = concern_store
        self._dcn_store = dcn_store
        self._lifecycle = lifecycle or ConcernLifecycleManager(
            concern_store=concern_store,
            dcn_store=dcn_store,
        )
        self._policy = policy or DefaultLifecycleControl()

    def run(self, now: datetime) -> dict:
        touched = 0
        weakened = 0
        archived = 0
        for concern in self._concern_store.iter_all():
            state = (concern.lifecycle_state or LifecycleState.CREATED.value).lower()
            if state not in _MAINTENANCE_STATES:
                continue
            step = self._policy.decay_step(concern)
            if step <= 0:
                continue
            updated = self._bump_decay(concern, step, now)
            touched += 1
            if self._policy.should_archive(updated):
                self._lifecycle.archive(updated, reason="heartbeat_decay")
                archived += 1
                continue
            if self._policy.should_weaken(updated):
                try:
                    self._lifecycle.weaken(updated, delta=0.05)
                    weakened += 1
                except Exception:
                    pass
        return {
            "touched": touched,
            "weakened": weakened,
            "archived": archived,
        }

    def _bump_decay(self, concern: Concern, step: float, now: datetime) -> Concern:
        activation = concern.activation_state or ActivationState()
        new_decay = min(1.0, float(activation.decay) + step)
        updated = concern.model_copy(
            update={
                "activation_state": activation.model_copy(update={"decay": new_decay}),
                "updated_at": now,
            }
        )
        return self._concern_store.upsert(updated)


__all__ = ["DecayWorker"]
