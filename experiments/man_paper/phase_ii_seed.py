"""H0 genesis: intent-aligned cortex + conserved reflex core (no plugin / SKILL seeds)."""

from __future__ import annotations

from opencoat_runtime_core.concern import ConcernBuilder, ConcernExtractor
from opencoat_runtime_core.ports import ConcernStore, DCNStore, LLMClient
from opencoat_runtime_protocol import (
    AdviceKind,
    AdviceType,
    AopAdvice,
    Concern,
    Pointcut,
    PointcutDef,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch

MAN_IDENTITY_PROMPT = (
    "Start up. You are a Self-Evolving Agent via Reward-Modulated Structural "
    "Plasticity over an Externally Reasoning LLM."
)

H0_CONSERVED_REFLEX_ID = "h0.conserved.fail-closed"
_SEED_REF = "phase_ii://man_identity"


def _h0_conserved_reflex_concern() -> Concern:
    """Minimal A_reflex / brainstem: deterministic fail-closed, not LLM-extracted."""
    return Concern(
        id=H0_CONSERVED_REFLEX_ID,
        name="H0 conserved fail-closed tool guard",
        description=(
            "Invariant reflex layer for H0: block destructive shell commands at the "
            "effector boundary. Not subject to morphogenetic rewrite."
        ),
        neuron_type="inhibitory",
        reflex=True,
        generated_type="safety_rule",
        generated_tags=["h0", "conserved", "reflex", "fail_closed"],
        pointcuts=[
            PointcutDef(
                id="pc-h0-tool",
                expression="before_tool_call()",
                joinpoints=["before_tool_call"],
                match=PointcutMatch(any_keywords=["rm -rf", "rm  -rf"]),
            ),
        ],
        advices=[
            AopAdvice(
                id="adv-h0-tool",
                kind=AdviceKind.BEFORE,
                pointcut_ref="pc-h0-tool",
                content="Refusing destructive shell command (H0 conserved core).",
                template=AdviceType.TOOL_GUARD,
                effect=WeavingPolicy(
                    mode=WeavingOperation.BLOCK,
                    level=WeavingLevel.TOOL_LEVEL,
                    target="tool_call.arguments",
                    priority=1.0,
                ),
            ),
        ],
    )


def _wire_cortex_pointcut(concern: Concern) -> Concern:
    """Cortex concern matches ``before_response`` (joinpoint-only, no NL keywords)."""
    return concern.model_copy(
        update={
            "pointcut": Pointcut(
                joinpoints=["before_response"],
                match=None,
            ),
        }
    )


def _extract_cortex_concern(
    llm: LLMClient,
    *,
    store: ConcernStore,
    dcn: DCNStore,
) -> Concern:
    """One plastic excitatory concern from the H0 startup prompt (intent alignment)."""
    extractor = ConcernExtractor(llm=llm, max_concerns_per_call=1)
    result = extractor.extract_for_intent_alignment(MAN_IDENTITY_PROMPT, ref=_SEED_REF)
    builder = ConcernBuilder(store=store)

    if result.candidates:
        concern = builder.build_or_update(result.candidates[0])
    else:
        fallback = Concern(
            id=ConcernBuilder.new_id(),
            name="Self-evolving agent (structural plasticity)",
            description=MAN_IDENTITY_PROMPT,
            generated_type="man_bootstrap",
            generated_tags=["man", "morphogenetic", "plasticity", "intent_alignment"],
        )
        concern = builder.build_or_update(fallback)

    concern = _wire_cortex_pointcut(concern)
    store.upsert(concern)
    dcn.add_node(concern)
    return concern


def seed_h0_graph(
    llm: LLMClient,
    *,
    store: ConcernStore,
    dcn: DCNStore,
    include_conserved_reflex: bool = True,
) -> Concern:
    """Seed the full H0 zygote: conserved reflex (optional) + one intent-aligned cortex."""
    if include_conserved_reflex:
        reflex = _h0_conserved_reflex_concern()
        store.upsert(reflex)
        dcn.add_node(reflex)
    return _extract_cortex_concern(llm, store=store, dcn=dcn)


def extract_bootstrap_concern(
    llm: LLMClient,
    *,
    store: ConcernStore,
    dcn: DCNStore,
) -> Concern:
    """Cortex-only alias. Prefer :func:`seed_h0_graph` for the canonical H0 zygote."""
    return seed_h0_graph(llm, store=store, dcn=dcn, include_conserved_reflex=True)


__all__ = [
    "H0_CONSERVED_REFLEX_ID",
    "MAN_IDENTITY_PROMPT",
    "extract_bootstrap_concern",
    "seed_h0_graph",
]
