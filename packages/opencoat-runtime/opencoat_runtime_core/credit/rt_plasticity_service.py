"""Daemon-side ``r_t`` append + consume pipeline (credit field warm path)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opencoat_runtime_storage.jsonl.r_t_recorder import RtJsonlRecorder, default_r_t_path

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.credit_field import CreditField
from opencoat_runtime_core.credit.plasticity_engine import (
    PlasticityEngine,
    ReweightStats,
    WarmStepStats,
)
from opencoat_runtime_core.credit.r_t_reader import RtJsonlTailReader
from opencoat_runtime_core.credit.r_t_record import RtRecord, reward_from_signal
from opencoat_runtime_core.credit.rt_buffer import ConcernRtBuffer
from opencoat_runtime_core.ports import ConcernStore, DCNStore


@dataclass
class RtPlasticityService:
    concern_store: ConcernStore
    dcn_store: DCNStore
    path: Path | str | None = None
    engine: PlasticityEngine = field(default_factory=PlasticityEngine)
    buffer: ConcernRtBuffer = field(default_factory=ConcernRtBuffer)
    _recorder: RtJsonlRecorder | None = field(default=None, repr=False)
    _reader: RtJsonlTailReader | None = field(default=None, repr=False)
    _lifecycle: ConcernLifecycleManager | None = field(default=None, repr=False)
    _credit: CreditField | None = field(default=None, repr=False)
    _consume_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    last_consume: ReweightStats | None = field(default=None, repr=False)
    last_warm: WarmStepStats | None = field(default=None, repr=False)
    _turn_concerns: dict[str, set[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        log_path = default_r_t_path() if self.path is None else Path(self.path)
        self._recorder = RtJsonlRecorder(log_path)
        self._recorder.__enter__()
        self._reader = RtJsonlTailReader(self._recorder.path)
        self._lifecycle = ConcernLifecycleManager(
            concern_store=self.concern_store,
            dcn_store=self.dcn_store,
        )
        self._credit = CreditField(concern_store=self.concern_store, buffer=self.buffer)

    def append(self, record: RtRecord) -> dict[str, Any]:
        assert self._recorder is not None and self._credit is not None
        normalized = record.model_copy(update={"r": reward_from_signal(record.signal)})
        self._credit.attribute(normalized)
        reflex = normalized.signal.reflex if isinstance(normalized.signal.reflex, dict) else {}
        policy_id = reflex.get("policy_id")
        if isinstance(policy_id, str) and policy_id.strip():
            turn = normalized.turn_id
            self._turn_concerns.setdefault(turn, set()).add(policy_id.strip())
        return self._recorder.append(normalized)

    def consume(self, *, max_records: int | None = None) -> WarmStepStats:
        """Single-consumer drain: credit attribute + warm plasticity."""
        assert self._reader is not None and self._lifecycle is not None
        with self._consume_lock:
            records = self._reader.read_new(max_records=max_records)
            co_pairs: list[tuple[str, str]] = []
            for members in self._turn_concerns.values():
                ordered = sorted(members)
                for i in range(len(ordered)):
                    for j in range(i + 1, len(ordered)):
                        co_pairs.append((ordered[i], ordered[j]))
            self._turn_concerns.clear()

            warm = self.engine.warm_step(
                records,
                concern_store=self.concern_store,
                dcn_store=self.dcn_store,
                lifecycle=self._lifecycle,
                co_pairs=co_pairs,
            )
            self.last_warm = warm
            self.last_consume = ReweightStats(
                read=len(records),
                reinforced=warm.reinforced,
                weakened=warm.weakened,
                skipped=warm.skipped,
            )
            return warm

    def cold_step(self) -> dict[str, int]:
        assert self._lifecycle is not None
        stats = self.engine.cold_step(
            concern_store=self.concern_store,
            dcn_store=self.dcn_store,
            lifecycle=self._lifecycle,
            buffer=self.buffer,
        )
        return stats.as_dict()

    def connectome_stats(self) -> dict[str, Any]:
        from opencoat_runtime_core.connectome.model import build_connectome_view

        view = build_connectome_view(
            concern_store=self.concern_store,
            dcn_store=self.dcn_store,
        )
        return {
            "aspects": len(view.aspects),
            "edges": len(view.edges),
            "reflex_core": sorted(view.reflex_core),
            "buffer_concerns": len(self.buffer.tracked_concern_ids()),
        }

    def stats(self) -> dict[str, Any]:
        assert self._recorder is not None and self._reader is not None
        payload: dict[str, Any] = {
            "path": str(self._recorder.path),
            "count": self._recorder.count,
            "cursor_offset": self._reader.cursor_offset(),
            "connectome": self.connectome_stats(),
        }
        if self.last_consume is not None:
            payload["last_consume"] = self.last_consume.as_dict()
        if self.last_warm is not None:
            payload["last_warm"] = self.last_warm.as_dict()
        return payload

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None


__all__ = ["RtPlasticityService"]
