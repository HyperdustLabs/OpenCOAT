"""Daemon-side ``r_t`` append + consume pipeline (credit field warm path)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.credit.plasticity_engine import PlasticityEngine, ReweightStats
from opencoat_runtime_core.credit.r_t_record import RtRecord, reward_from_signal
from opencoat_runtime_core.credit.r_t_reader import RtJsonlTailReader
from opencoat_runtime_core.ports import ConcernStore, DCNStore
from opencoat_runtime_storage.jsonl.r_t_recorder import RtJsonlRecorder, default_r_t_path


@dataclass
class RtPlasticityService:
    concern_store: ConcernStore
    dcn_store: DCNStore
    path: Path | str | None = None
    engine: PlasticityEngine = field(default_factory=PlasticityEngine)
    _recorder: RtJsonlRecorder | None = field(default=None, repr=False)
    _reader: RtJsonlTailReader | None = field(default=None, repr=False)
    _lifecycle: ConcernLifecycleManager | None = field(default=None, repr=False)
    _consume_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    last_consume: ReweightStats | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        log_path = default_r_t_path() if self.path is None else Path(self.path)
        self._recorder = RtJsonlRecorder(log_path)
        self._recorder.__enter__()
        self._reader = RtJsonlTailReader(self._recorder.path)
        self._lifecycle = ConcernLifecycleManager(
            concern_store=self.concern_store,
            dcn_store=self.dcn_store,
        )

    def append(self, record: RtRecord) -> dict[str, Any]:
        assert self._recorder is not None
        normalized = record.model_copy(update={"r": reward_from_signal(record.signal)})
        return self._recorder.append(normalized)

    def consume(self, *, max_records: int | None = None) -> ReweightStats:
        """Single-consumer drain: safe under concurrent JSON-RPC and heartbeat."""
        assert self._reader is not None and self._lifecycle is not None
        with self._consume_lock:
            records = self._reader.read_new(max_records=max_records)
            stats = self.engine.reweight(
                records,
                concern_store=self.concern_store,
                lifecycle=self._lifecycle,
            )
            self.last_consume = stats
            return stats

    def stats(self) -> dict[str, Any]:
        assert self._recorder is not None and self._reader is not None
        payload: dict[str, Any] = {
            "path": str(self._recorder.path),
            "count": self._recorder.count,
            "cursor_offset": self._reader.cursor_offset(),
        }
        if self.last_consume is not None:
            payload["last_consume"] = self.last_consume.as_dict()
        return payload

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None


__all__ = ["RtPlasticityService"]
