"""GET /v1/injection/{weave_id} — replay the injection produced for one weave run."""

from __future__ import annotations

from opencoat_runtime_protocol import ConcernInjection


class InjectionAPI:
    def get(self, weave_id: str) -> ConcernInjection | None:
        raise NotImplementedError
