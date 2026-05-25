"""Context-bucket reward baseline ``b`` (morphogenetic §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock


@dataclass
class RewardBaseline:
    """Context baseline ``b`` for advantage = ``r - b``.

    ``ema_alpha`` in (0, 1]: exponential smoothing (lower → slower baseline,
    sustained advantage on success streaks). ``ema_alpha=1`` uses the
    cumulative mean (legacy default).
    """

    ema_alpha: float = 1.0
    _sums: dict[str, float] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)
    _ema: dict[str, float] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def bucket_for(self, *, joinpoint: str, session_id: str = "default") -> str:
        return f"{session_id}:{joinpoint}"

    def baseline(self, bucket: str) -> float:
        with self._lock:
            if self.ema_alpha >= 1.0:
                count = self._counts.get(bucket, 0)
                if count == 0:
                    return 0.0
                return self._sums[bucket] / count
            return self._ema.get(bucket, 0.0)

    def update(self, bucket: str, reward: float) -> float:
        with self._lock:
            if self.ema_alpha >= 1.0:
                self._sums[bucket] = self._sums.get(bucket, 0.0) + reward
                self._counts[bucket] = self._counts.get(bucket, 0) + 1
                return self._sums[bucket] / self._counts[bucket]
            prev = self._ema.get(bucket, 0.0)
            b = prev + self.ema_alpha * (reward - prev)
            self._ema[bucket] = b
            self._counts[bucket] = self._counts.get(bucket, 0) + 1
            return b

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            out: dict[str, dict[str, float]] = {
                "sums": dict(self._sums),
                "counts": {k: float(v) for k, v in self._counts.items()},
            }
            if self.ema_alpha < 1.0:
                out["ema"] = dict(self._ema)
                out["ema_alpha"] = {"value": self.ema_alpha}
            return out

    def load_snapshot(self, data: dict[str, dict[str, float]]) -> None:
        with self._lock:
            self._sums = {str(k): float(v) for k, v in dict(data.get("sums") or {}).items()}
            self._counts = {str(k): int(v) for k, v in dict(data.get("counts") or {}).items()}
            self._ema = {str(k): float(v) for k, v in dict(data.get("ema") or {}).items()}
            alpha_row = data.get("ema_alpha") or {}
            if isinstance(alpha_row, dict) and "value" in alpha_row:
                self.ema_alpha = float(alpha_row["value"])


__all__ = ["RewardBaseline"]
