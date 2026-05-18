"""SimpleChatAgent — minimal host that drives :class:`OpenCOATRuntime`.

The agent is intentionally <100 lines of business logic. It owns:

* the runtime instance (in-memory stores + stub LLM),
* a hand-authored set of concerns,
* a single ``handle`` method that walks one turn end-to-end and returns
  a structured :class:`TurnReport`.

It is **not** an example of "how to build a real agent" — it is the
smallest thing that exercises every M1 module the runtime currently
ships, so a developer can read it top to bottom and trace a turn.

Pipeline per ``handle(user_text)``:

    user_text
        → JoinpointEvent("before_response", payload={"raw_text": user_text})
        → OpenCOATRuntime.on_joinpoint   (match · coordinate · advise · weave)
        → host LLM call (stub)
        → ConcernVerifier.verify_turn
        → TurnReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.concern.verifier import ConcernVerifier, VerificationResult
from opencoat_runtime_core.llm import StubLLMClient
from opencoat_runtime_protocol import (
    Concern,
    ConcernInjection,
    ConcernVector,
    JoinpointEvent,
)
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

from .concerns import seed_concerns


@dataclass(frozen=True)
class TurnReport:
    """One turn's worth of host-visible state.

    Attached to the agent's return value so the smoke test (and any
    future CLI) can render it without poking at runtime internals.
    """

    user_text: str
    response: str
    injection: ConcernInjection
    vector: ConcernVector
    verifications: list[VerificationResult] = field(default_factory=list)

    @property
    def active_concern_ids(self) -> list[str]:
        return [a.concern_id for a in self.vector.active_concerns]

    @property
    def passed_verifications(self) -> int:
        return sum(1 for v in self.verifications if v.satisfied)


class SimpleChatAgent:
    """Tiny host wired against an in-process :class:`OpenCOATRuntime`.

    Every collaborator is swappable. The default constructor mirrors the
    most opinionated shape (memory stores + stub LLM + bundled defaults)
    so the example is hermetic; tests and richer demos can pass their
    own runtime to inspect behaviour under non-default budgets.
    """

    def __init__(
        self,
        *,
        runtime: OpenCOATRuntime | None = None,
        concerns: list[Concern] | None = None,
        # The verifier intentionally shares the runtime's LLM so any
        # future swap (real provider in M2) lights up both sides at
        # once. ``StubLLMClient`` makes verifier and joinpoint pipeline
        # deterministic in CI.
        verifier: ConcernVerifier | None = None,
        session_id: str | None = None,
    ) -> None:
        self._runtime = runtime or _default_runtime()
        self._verifier = verifier or ConcernVerifier(llm=self._runtime._llm)  # type: ignore[attr-defined]
        self._session_id = session_id or f"session-{uuid4().hex[:8]}"

        # ``concerns is None`` ≠ ``concerns == []``: an explicit empty
        # list is a deliberate "no demo concerns, please" opt-out (e.g.
        # tests that want a clean baseline or callers that will
        # ``upsert`` their own set later). The previous ``concerns or
        # seed_concerns()`` form quietly re-seeded the demos in that
        # case — Codex P2 on PR-6.
        seeded = seed_concerns() if concerns is None else concerns
        for concern in seeded:
            self._runtime.concern_store.upsert(concern)

    @property
    def runtime(self) -> OpenCOATRuntime:
        return self._runtime

    @property
    def session_id(self) -> str:
        return self._session_id

    def handle(self, user_text: str) -> TurnReport:
        """Run one turn through the runtime and return a structured report."""
        joinpoint = JoinpointEvent(
            id=f"jp-{uuid4().hex[:12]}",
            level=2,  # "message" level — see JoinpointLevel.MESSAGE
            name="before_response",
            host="example.simple_chat_agent",
            agent_session_id=self._session_id,
            ts=datetime.now(UTC),
            payload={"raw_text": user_text, "text": user_text},
        )

        injection = self._runtime.on_joinpoint(joinpoint)
        # ``on_joinpoint`` only returns ``None`` when the host explicitly
        # opts in via ``return_none_when_empty``; the agent never does.
        assert injection is not None
        vector = self._runtime.current_vector()
        assert vector is not None  # always populated when we got an injection

        response = self._compose_response(user_text, injection)
        verifications = self._verifier.verify_turn(
            active=vector,
            concerns=list(self._runtime.concern_store.iter_all()),
            host_output=response,
        )

        return TurnReport(
            user_text=user_text,
            response=response,
            injection=injection,
            vector=vector,
            verifications=verifications,
        )

    # ------------------------------------------------------------------
    # Response synthesis
    # ------------------------------------------------------------------

    def _compose_response(self, user_text: str, injection: ConcernInjection) -> str:
        """Synthesize a placeholder reply that *honours* the injection.

        A real host would feed ``injection`` into its prompt builder and
        let the LLM produce the answer. The example keeps things
        hermetic by composing a deterministic string that:

        * echoes the user's question,
        * embeds every injected advice (so verifier rules can hit),
        * leaves PII redaction to the user since the stub LLM has no
          way to know what is sensitive.

        This is enough to exercise every verification rule attached to
        the bundled concerns without dragging a real LLM into CI.
        """
        # ``Injection.advice_type`` is serialised as the enum's string
        # value (envelopes use ``use_enum_values=True``), so ``inj.advice_type``
        # is already a plain ``str`` here — no ``.value`` access.
        directives = "\n".join(
            f"- {inj.advice_type or 'unspecified'}: {inj.content}" for inj in injection.injections
        )
        # Include a citation marker so the ``cite-sources`` verification
        # rule passes by default. The smoke test deliberately exercises
        # both "rule passes" and "rule fails" code paths by toggling
        # this on a per-call override (see ``handle`` callers in tests).
        return f"You asked: {user_text}\nFollowing guidance:\n{directives}\nAnswer: see [1]."


def _default_runtime() -> OpenCOATRuntime:
    return OpenCOATRuntime(
        RuntimeConfig(),
        concern_store=MemoryConcernStore(),
        dcn_store=MemoryDCNStore(),
        llm=StubLLMClient(),
    )


__all__ = ["SimpleChatAgent", "TurnReport"]
