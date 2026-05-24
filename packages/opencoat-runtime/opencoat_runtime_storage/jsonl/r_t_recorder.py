"""Append-only JSONL writer for ``r_t`` outcome records."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, TextIO

from opencoat_runtime_core.credit.r_t_record import RtRecord


class RtJsonlRecorder:
    """Thread-safe append-only ``r_t`` log (v0.3 credit field input)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._fp: TextIO | None = None
        self._count = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def count(self) -> int:
        return self._count

    def __enter__(self) -> RtJsonlRecorder:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self._path.exists():
                with self._path.open(encoding="utf-8") as rf:
                    self._count = sum(1 for line in rf if line.strip())
            self._fp = self._path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._fp is not None:
                self._fp.flush()
                self._fp.close()
                self._fp = None

    def append(self, record: RtRecord) -> dict[str, Any]:
        with self._lock:
            if self._fp is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._fp = self._path.open("a", encoding="utf-8")
            payload = record.to_jsonl()
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self._fp.write(line + "\n")
            self._fp.flush()
            self._count += 1
            return payload


def default_r_t_path() -> Path:
    return Path.home() / ".opencoat" / "r_t.jsonl"


__all__ = ["RtJsonlRecorder", "default_r_t_path"]
