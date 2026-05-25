"""Temperature schedules for MAN stochastic graph rewrites."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemperatureSchedule:
    """Deterministic ``T(t)`` used by slow stochastic graph rewrites."""

    kind: str = "constant"
    initial: float = 1.0
    final: float = 0.1
    decay: float = 0.99
    steps: int = 100
    floor: float = 1e-6

    def at(self, step: int) -> float:
        if self.initial <= 0.0:
            raise ValueError("initial temperature must be positive")
        if self.final <= 0.0:
            raise ValueError("final temperature must be positive")
        if self.floor <= 0.0:
            raise ValueError("floor temperature must be positive")
        t = max(0, step)
        kind = self.kind.lower().strip()
        if kind == "constant":
            value = self.initial
        elif kind == "exponential":
            value = max(self.final, self.initial * (self.decay**t))
        elif kind == "linear":
            horizon = max(1, self.steps)
            alpha = min(1.0, t / horizon)
            value = (
                self.final if alpha >= 1.0 else self.initial + alpha * (self.final - self.initial)
            )
        else:
            raise ValueError(f"unsupported temperature schedule kind: {self.kind!r}")
        return max(self.floor, value)


__all__ = ["TemperatureSchedule"]
