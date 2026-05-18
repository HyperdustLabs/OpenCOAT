"""CodingAgent — coding-agent host wired against :class:`OpenCOATRuntime`.

The agent extends the M1 ``SimpleChatAgent`` along three M2 axes:

1. **Real LLM by default.**  The constructor pulls a provider via
   :func:`select_llm`, which auto-detects OpenAI / Anthropic / Azure
   from the environment and falls back to the stub for hermetic CI.
2. **Real LLM in the response path.**  ``_compose_response`` calls
   ``self._llm.chat(...)`` instead of synthesizing a string.  The
   woven injection becomes the system message; the user's prompt is
   the user message.  With the stub this returns a deterministic
   canned reply; with a real provider it returns a real model
   answer.
3. **Lifecycle bookkeeping.**  After each turn the agent calls
   :meth:`ConcernLifecycleManager.reinforce` for every concern that
   actually fired, demonstrating that the lifecycle manager landed
   in PR-11 plugs cleanly into the joinpoint pipeline.

The agent is still under ~150 lines of business logic — the point is
to be readable end to end.  ``handle`` walks the same pipeline as
PR-6's ``SimpleChatAgent.handle``, with the LLM call swapped in for
the synthetic reply and the lifecycle calls appended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from opencoat_runtime_core import OpenCOATRuntime, RuntimeConfig
from opencoat_runtime_core.concern.lifecycle import ConcernLifecycleManager
from opencoat_runtime_core.concern.verifier import ConcernVerifier, VerificationResult
from opencoat_runtime_core.ports import LLMClient
from opencoat_runtime_protocol import (
    Concern,
    ConcernInjection,
    ConcernVector,
    JoinpointEvent,
)
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

from .concerns import seed_concerns
from .llm import select_llm


@dataclass(frozen=True)
class TurnReport:
    """One turn's worth of host-visible state.

    Mirrors :class:`examples.01_simple_chat_agent.TurnReport` with
    two M2-specific additions: ``llm_label`` records which provider
    actually answered, and ``reinforced_concern_ids`` records which
    concerns the lifecycle manager touched after the turn.
    """

    user_text: str
    response: str
    injection: ConcernInjection
    vector: ConcernVector
    llm_label: str
    verifications: list[VerificationResult] = field(default_factory=list)
    reinforced_concern_ids: list[str] = field(default_factory=list)

    @property
    def active_concern_ids(self) -> list[str]:
        return [a.concern_id for a in self.vector.active_concerns]

    @property
    def passed_verifications(self) -> int:
        return sum(1 for v in self.verifications if v.satisfied)


class CodingAgent:
    """Coding-assistant host driven by a real LLM (or the stub).

    Parameters
    ----------
    runtime:
        Optional pre-built :class:`OpenCOATRuntime`.  If ``None``, the
        agent constructs one with in-memory stores and the
        env-detected LLM.
    llm:
        Optional :class:`LLMClient` override used both for the
        runtime and for the response path.  When the caller passes
        an explicit ``runtime``, this is ignored — the runtime's
        own ``llm`` wins.
    llm_label:
        Optional label that will be shown in
        :class:`TurnReport.llm_label`.  Defaults to ``"<custom>"``
        when an explicit ``llm`` was passed and to whatever
        :func:`select_llm` returned otherwise.
    concerns:
        Optional list of :class:`Concern` envelopes to seed the
        store with.  Same opt-out semantics as
        :class:`SimpleChatAgent`: ``None`` → demo seed,
        ``[]`` → empty store on purpose.
    verifier:
        Optional :class:`ConcernVerifier` override.  Defaults to one
        sharing the runtime's LLM.
    lifecycle:
        Optional :class:`ConcernLifecycleManager` override.  Defaults
        to one wired to the runtime's stores with a fresh real-time
        clock.
    session_id:
        Optional session-id override for joinpoint tagging.
    """

    def __init__(
        self,
        *,
        runtime: OpenCOATRuntime | None = None,
        llm: LLMClient | None = None,
        llm_label: str | None = None,
        concerns: list[Concern] | None = None,
        verifier: ConcernVerifier | None = None,
        lifecycle: ConcernLifecycleManager | None = None,
        session_id: str | None = None,
    ) -> None:
        if runtime is None:
            client, label = (llm, llm_label or "<custom>") if llm is not None else select_llm()
            runtime = OpenCOATRuntime(
                RuntimeConfig(),
                concern_store=MemoryConcernStore(),
                dcn_store=MemoryDCNStore(),
                llm=client,
            )
            self._llm_label = label
        else:
            # When the caller pre-built the runtime, trust its LLM.
            # Pulling the private attr keeps the verifier + label in
            # sync with the actual answering client.
            self._llm_label = llm_label or "<custom>"

        self._runtime = runtime
        # The runtime owns the canonical LLM; the response path goes
        # through it directly so a future swap (e.g. a per-turn
        # provider override) lights up in one place.
        self._llm: LLMClient = self._runtime._llm  # type: ignore[attr-defined]
        self._verifier = verifier or ConcernVerifier(llm=self._llm)
        self._lifecycle = lifecycle or ConcernLifecycleManager(
            concern_store=self._runtime.concern_store,
            dcn_store=self._runtime.dcn_store,
        )
        self._session_id = session_id or f"session-{uuid4().hex[:8]}"

        # Same opt-out semantics as the M1 chat-agent example. The
        # joinpoint pipeline will lazily ``add_node`` to the DCN on first
        # activation, so we only seed the ConcernStore here.
        seeded = seed_concerns() if concerns is None else concerns
        for concern in seeded:
            self._runtime.concern_store.upsert(concern)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def runtime(self) -> OpenCOATRuntime:
        return self._runtime

    @property
    def llm_label(self) -> str:
        return self._llm_label

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def lifecycle(self) -> ConcernLifecycleManager:
        return self._lifecycle

    # ------------------------------------------------------------------
    # Turn pipeline
    # ------------------------------------------------------------------

    def handle(self, user_text: str) -> TurnReport:
        """Run one turn: match → weave → LLM → verify → reinforce."""
        joinpoint = JoinpointEvent(
            id=f"jp-{uuid4().hex[:12]}",
            level=2,  # JoinpointLevel.MESSAGE
            name="before_response",
            host="example.coding_agent_demo",
            agent_session_id=self._session_id,
            ts=datetime.now(UTC),
            payload={"raw_text": user_text, "text": user_text},
        )

        injection = self._runtime.on_joinpoint(joinpoint)
        assert injection is not None
        vector = self._runtime.current_vector()
        assert vector is not None

        response = self._compose_response(user_text, injection)
        verifications = self._verifier.verify_turn(
            active=vector,
            concerns=list(self._runtime.concern_store.iter_all()),
            host_output=response,
        )

        # Lifecycle bookkeeping: every concern that activated on this
        # turn gets a reinforce() bump, mirroring how a long-lived
        # production agent would record activation events. We
        # deliberately don't weaken the dormant concerns — absence on
        # one turn isn't evidence the rule is wrong, and a blanket
        # weaken would cause a slow drift to score=0 over a long
        # session.
        reinforced: list[str] = []
        for active in vector.active_concerns:
            stored = self._runtime.concern_store.get(active.concern_id)
            if stored is None:
                continue
            self._lifecycle.reinforce(stored)
            reinforced.append(active.concern_id)

        return TurnReport(
            user_text=user_text,
            response=response,
            injection=injection,
            vector=vector,
            llm_label=self._llm_label,
            verifications=verifications,
            reinforced_concern_ids=reinforced,
        )

    # ------------------------------------------------------------------
    # Response synthesis
    # ------------------------------------------------------------------

    def _compose_response(self, user_text: str, injection: ConcernInjection) -> str:
        """Call the LLM with the woven injection as the system prompt."""
        system_prompt = _build_system_prompt(injection)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        # Cap at 600 tokens — the demo answers don't need to be long
        # and a tighter cap keeps real-LLM bills predictable.
        return self._llm.chat(messages=messages, max_tokens=600, temperature=0.0)


# ---------------------------------------------------------------------------
# System-prompt builder
# ---------------------------------------------------------------------------


_SYSTEM_PREAMBLE = (
    "You are a careful Python coding assistant. The OpenCOAT runtime "
    "has matched the following concerns to this turn — treat them "
    "as binding constraints on your answer. Each line is one "
    "directive."
)


def _build_system_prompt(injection: ConcernInjection) -> str:
    """Render the woven injection into a single system message."""
    if not injection.injections:
        return f"{_SYSTEM_PREAMBLE}\n\n(no concerns matched on this turn — answer normally.)"
    lines: list[str] = [_SYSTEM_PREAMBLE, ""]
    for inj in injection.injections:
        # Envelopes use ``use_enum_values=True`` so the enum-valued
        # fields are already plain strings here.
        kind = inj.advice_type or "directive"
        lines.append(f"- [{kind}] {inj.content}")
    lines.append("")
    lines.append(
        "If a directive forbids something the user asked for, refuse "
        "and explain briefly. Keep code blocks minimal and copy-pasteable."
    )
    return "\n".join(lines)


__all__ = ["CodingAgent", "TurnReport"]
