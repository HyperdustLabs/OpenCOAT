"""Heartbeat + periodic worker scheduler."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger("opencoat_runtime_daemon.scheduler")


class Scheduler:
    """Background thread that invokes a tick callback on a fixed interval."""

    def __init__(
        self,
        tick: Callable[[], None],
        *,
        heartbeat_interval_seconds: float = 30.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        self._tick = tick
        self._interval = heartbeat_interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="opencoat-heartbeat",
            daemon=True,
        )
        self._thread.start()
        logger.info("heartbeat scheduler started (interval=%ss)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._interval + 2.0)
        self._thread = None
        logger.info("heartbeat scheduler stopped")

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._tick()
            except Exception:
                logger.exception("heartbeat tick failed")
