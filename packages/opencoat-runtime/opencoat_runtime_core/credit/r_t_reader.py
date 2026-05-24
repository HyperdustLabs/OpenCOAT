"""Tail-read ``r_t.jsonl`` with a durable byte cursor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opencoat_runtime_core.credit.r_t_record import RtRecord


class RtJsonlTailReader:
    """Read newly appended ``r_t`` lines since the last consume."""

    def __init__(self, path: Path, *, cursor_path: Path | None = None) -> None:
        self._path = path
        self._cursor_path = cursor_path or path.with_suffix(".cursor.json")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def cursor_path(self) -> Path:
        return self._cursor_path

    def cursor_offset(self) -> int:
        if not self._cursor_path.exists():
            return 0
        try:
            data = json.loads(self._cursor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        offset = data.get("offset")
        return int(offset) if isinstance(offset, int) and offset >= 0 else 0

    def read_new(self, *, max_records: int | None = None) -> list[RtRecord]:
        if not self._path.exists():
            return []
        offset = self.cursor_offset()
        records: list[RtRecord] = []
        with self._path.open("rb") as fh:
            fh.seek(offset)
            while True:
                line = fh.readline()
                if not line:
                    break
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                row: dict[str, Any] = json.loads(text)
                records.append(RtRecord.model_validate(row))
                if max_records is not None and len(records) >= max_records:
                    break
            new_offset = fh.tell()
        if new_offset > offset:
            self._write_cursor(new_offset)
        return records

    def _write_cursor(self, offset: int) -> None:
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"offset": offset, "path": str(self._path)}
        self._cursor_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


__all__ = ["RtJsonlTailReader"]
