"""Heartbeat scheduler."""

from __future__ import annotations

import threading
import time

from opencoat_runtime_daemon.scheduler import Scheduler


def test_scheduler_invokes_tick() -> None:
    hits: list[int] = []
    lock = threading.Lock()

    def tick() -> None:
        with lock:
            hits.append(1)

    sched = Scheduler(tick, heartbeat_interval_seconds=0.05)
    sched.start()
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with lock:
                if hits:
                    break
            time.sleep(0.01)
        with lock:
            assert len(hits) >= 1
    finally:
        sched.stop()
