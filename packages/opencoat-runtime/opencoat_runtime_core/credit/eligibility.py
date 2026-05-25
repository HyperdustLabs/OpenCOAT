"""Eligibility traces ``e_a``, ``e_s`` (morphogenetic §3, tier-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock


def _edge_key(src: str, dst: str, relation: str) -> tuple[str, str, str]:
    return (src, dst, relation)


@dataclass
class EligibilityField:
    """``e ← λ·e + α·part`` for aspects and synapses (deterministic, replayable)."""

    trace_lambda: float = 0.9
    trace_alpha: float = 1.0
    _aspect: dict[str, float] = field(default_factory=dict)
    _synapse: dict[tuple[str, str, str], float] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def touch_aspect(self, concern_id: str, *, part: float = 1.0) -> float:
        with self._lock:
            prev = self._aspect.get(concern_id, 0.0)
            nxt = self.trace_lambda * prev + self.trace_alpha * max(0.0, part)
            self._aspect[concern_id] = nxt
            return nxt

    def touch_synapse(
        self,
        src: str,
        dst: str,
        *,
        relation: str = "activates",
        part: float = 1.0,
    ) -> float:
        key = _edge_key(src, dst, relation)
        with self._lock:
            prev = self._synapse.get(key, 0.0)
            nxt = self.trace_lambda * prev + self.trace_alpha * max(0.0, part)
            self._synapse[key] = nxt
            return nxt

    def aspect_e(self, concern_id: str) -> float:
        with self._lock:
            return self._aspect.get(concern_id, 0.0)

    def synapse_e(self, src: str, dst: str, *, relation: str = "activates") -> float:
        with self._lock:
            return self._synapse.get(_edge_key(src, dst, relation), 0.0)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "aspect": dict(self._aspect),
                "synapse": {f"{a}->{b}:{r}": v for (a, b, r), v in self._synapse.items()},
            }

    def load_snapshot(self, data: dict[str, object]) -> None:
        with self._lock:
            self._aspect = {str(k): float(v) for k, v in dict(data.get("aspect") or {}).items()}
            raw_syn = dict(data.get("synapse") or {})
            self._synapse = {}
            for key, val in raw_syn.items():
                if "->" not in key:
                    continue
                left, rel = key.rsplit(":", 1)
                src, dst = left.split("->", 1)
                self._synapse[_edge_key(src, dst, rel)] = float(val)


__all__ = ["EligibilityField"]
