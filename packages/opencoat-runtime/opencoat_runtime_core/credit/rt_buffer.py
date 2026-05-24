"""Per-concern ``r_t`` sample buffer for split guards (morphogenetic §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock


@dataclass(frozen=True)
class RtSample:
    r: float
    feature: str


@dataclass
class ConcernRtBuffer:
    """Sliding window of ``(r, φ)`` rows keyed by concern id."""

    max_samples: int = 256
    _samples: dict[str, list[RtSample]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def append(self, concern_id: str, *, r: float, feature: str = "") -> None:
        with self._lock:
            rows = self._samples.setdefault(concern_id, [])
            rows.append(RtSample(r=r, feature=feature or ""))
            if len(rows) > self.max_samples:
                del rows[: len(rows) - self.max_samples]

    def samples(self, concern_id: str) -> list[RtSample]:
        with self._lock:
            return list(self._samples.get(concern_id, []))

    def count(self, concern_id: str) -> int:
        return len(self.samples(concern_id))

    def reward_variance(self, concern_id: str) -> float:
        rows = self.samples(concern_id)
        if len(rows) < 2:
            return 0.0
        mean = sum(s.r for s in rows) / len(rows)
        return sum((s.r - mean) ** 2 for s in rows) / len(rows)

    def clear(self, concern_id: str | None = None) -> None:
        with self._lock:
            if concern_id is None:
                self._samples.clear()
            else:
                self._samples.pop(concern_id, None)

    def tracked_concern_ids(self) -> list[str]:
        with self._lock:
            return list(self._samples.keys())


__all__ = ["ConcernRtBuffer", "RtSample"]
