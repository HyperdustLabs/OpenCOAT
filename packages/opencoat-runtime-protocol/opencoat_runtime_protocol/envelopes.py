"""Pydantic envelopes mirroring the JSON Schemas in ``schemas/``.

Field semantics match the schemas 1:1. Where the schema allows a richer JSON
shape than is convenient in Python (e.g. polymorphic payloads), we expose
permissive ``dict``/``Any`` fields; the schemas remain the strict source of
truth for validation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enumerations (mirror schema enums)
# ---------------------------------------------------------------------------


class ConcernKind(StrEnum):
    CONCERN = "concern"
    META_CONCERN = "meta_concern"


class LifecycleState(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    REINFORCED = "reinforced"
    WEAKENED = "weakened"
    MERGED = "merged"
    FROZEN = "frozen"
    ARCHIVED = "archived"
    DELETED = "deleted"
    REVIVED = "revived"


class AdviceKind(StrEnum):
    """AOP (AspectJ) advice kinds — executable joinpoint semantics."""

    BEFORE = "before"
    AFTER = "after"
    AROUND = "around"
    AFTER_RETURNING = "after_returning"
    AFTER_THROWING = "after_throwing"


class ConcernGraphEdgeType(StrEnum):
    """AOP graph edges in the Concern Graph / DCN."""

    DEFINES = "defines"
    SELECTS = "selects"
    OWNS = "owns"
    RUNS_AT = "runs_at"
    BINDS = "binds"
    DECLARES_PRECEDENCE_OVER = "declares_precedence_over"
    INTRODUCES = "introduces"
    ADVISES = "advises"
    ADVICE_EXECUTION = "advice_execution"


class ConcernRelationType(StrEnum):
    ACTIVATES = "activates"
    SUPPRESSES = "suppresses"
    CONSTRAINS = "constrains"
    VERIFIES = "verifies"
    CONFLICTS_WITH = "conflicts_with"
    DEPENDS_ON = "depends_on"
    GENERALIZES = "generalizes"
    SPECIALIZES = "specializes"
    DUPLICATES = "duplicates"
    DERIVED_FROM = "derived_from"
    UPDATES = "updates"
    REPLACES = "replaces"
    SUPPORTS = "supports"
    #: AOP ``declare precedence`` (AspectJ) between concerns (preferred over ``suppresses``).
    DECLARES_PRECEDENCE_OVER = "declares_precedence_over"


class JoinpointLevel(StrEnum):
    RUNTIME = "runtime"
    LIFECYCLE = "lifecycle"
    MESSAGE = "message"
    PROMPT_SECTION = "prompt_section"
    SPAN = "span"
    TOKEN = "token"
    STRUCTURE_FIELD = "structure_field"
    THOUGHT_UNIT = "thought_unit"


class AdviceType(StrEnum):
    REASONING_GUIDANCE = "reasoning_guidance"
    PLANNING_GUIDANCE = "planning_guidance"
    DECISION_GUIDANCE = "decision_guidance"
    TOOL_GUARD = "tool_guard"
    RESPONSE_REQUIREMENT = "response_requirement"
    VERIFICATION_RULE = "verification_rule"
    MEMORY_WRITE_GUARD = "memory_write_guard"
    REFLECTION_PROMPT = "reflection_prompt"
    REWRITE_GUIDANCE = "rewrite_guidance"
    SUPPRESS_INSTRUCTION = "suppress_instruction"
    ESCALATION_NOTICE = "escalation_notice"


class WeavingOperation(StrEnum):
    INSERT = "insert"
    REPLACE = "replace"
    SUPPRESS = "suppress"
    ANNOTATE = "annotate"
    WARN = "warn"
    VERIFY = "verify"
    REWRITE = "rewrite"
    DEFER = "defer"
    ESCALATE = "escalate"
    BLOCK = "block"
    COMPRESS = "compress"


class WeavingLevel(StrEnum):
    PROMPT_LEVEL = "prompt_level"
    SPAN_LEVEL = "span_level"
    TOKEN_LEVEL = "token_level"
    TOOL_LEVEL = "tool_level"
    MEMORY_LEVEL = "memory_level"
    OUTPUT_LEVEL = "output_level"
    VERIFICATION_LEVEL = "verification_level"
    REFLECTION_LEVEL = "reflection_level"


class GovernanceCapability(StrEnum):
    EXTRACTION_CONTROL = "extraction_control"
    SEPARATION_CONTROL = "separation_control"
    ACTIVATION_CONTROL = "activation_control"
    CONFLICT_RESOLUTION = "conflict_resolution"
    VERIFICATION_CONTROL = "verification_control"
    LIFECYCLE_CONTROL = "lifecycle_control"
    BUDGET_CONTROL = "budget_control"
    EVOLUTION_CONTROL = "evolution_control"


# ---------------------------------------------------------------------------
# Base config — all envelopes forbid unknown fields by default.
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_enum_values=True,
    )


# ---------------------------------------------------------------------------
# Joinpoint
# ---------------------------------------------------------------------------


class JoinpointSelector(_Base):
    level: JoinpointLevel | None = None
    path: str | None = None
    name: str | None = None
    semantic_type: str | None = None
    match: list[str] | None = None
    field: str | None = None


class JoinpointEvent(_Base):
    id: str
    level: int = Field(ge=0, le=7)
    name: str
    host: str
    agent_session_id: str | None = None
    #: Host agent dialog round (e.g. OpenClaw ``runId``). Not the OpenCOAT weave id.
    host_round_id: str | None = None
    ts: datetime
    payload: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_turn_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("turn_id") is not None:
            data = dict(data)
            if data.get("host_round_id") is None:
                data["host_round_id"] = data["turn_id"]
            data.pop("turn_id", None)
        return data


# ---------------------------------------------------------------------------
# Pointcut
# ---------------------------------------------------------------------------


class StructureMatch(_Base):
    field: str
    operator: Literal["==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains"]
    value: Any | None = None
    value_ref: str | None = None


class ConfidenceMatch(_Base):
    op: Literal["<", "<=", ">", ">="]
    threshold: float = Field(ge=0.0, le=1.0)


class RiskMatch(_Base):
    op: Literal["==", ">=", "<="]
    level: Literal["low", "medium", "high", "critical"]


class ClaimMatch(_Base):
    claim_type: str | None = None
    evidence_required: bool | None = None


class PointcutMatch(_Base):
    any_keywords: list[str] | None = None
    all_keywords: list[str] | None = None
    regex: str | None = None
    semantic_intent: str | None = None
    structure: StructureMatch | None = None
    confidence: ConfidenceMatch | None = None
    risk: RiskMatch | None = None
    history: dict[str, Any] | None = None
    claim: ClaimMatch | None = None


class ContextPredicate(_Base):
    key: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "not_in"]
    value: Any | None = None
    value_ref: str | None = None


class Pointcut(_Base):
    joinpoints: list[str] | list[JoinpointSelector] = Field(default_factory=list)
    match: PointcutMatch | None = None
    context_predicates: list[ContextPredicate] = Field(default_factory=list)


class PointcutDef(_Base):
    """AOP pointcut (optional ``expression`` + structured ``match``)."""

    id: str = "pc-default"
    expression: str | None = None
    joinpoints: list[str] | list[JoinpointSelector] = Field(default_factory=list)
    match: PointcutMatch | None = None
    context_predicates: list[ContextPredicate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Advice / Weaving
# ---------------------------------------------------------------------------


class Advice(_Base):
    type: AdviceType
    content: str = Field(min_length=1)
    rationale: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    params: dict[str, Any] | None = None


class WeavingPolicy(_Base):
    mode: WeavingOperation | None = None
    level: WeavingLevel | None = None
    target: str | None = None
    max_tokens: int = Field(default=200, ge=1)
    priority: float = Field(default=0.5, ge=0.0, le=1.0)


class AopAdvice(_Base):
    """AOP advice bound to a pointcut ref."""

    id: str = "adv-default"
    kind: AdviceKind
    pointcut_ref: str = "pc-default"
    content: str = Field(min_length=1)
    template: AdviceType | None = None
    rationale: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    params: dict[str, Any] | None = None
    effect: WeavingPolicy | None = None


class WeavingOp(_Base):
    target: str
    operation: WeavingOperation
    level: WeavingLevel | None = None
    content: str | None = None
    condition: str | None = None
    priority: float | None = Field(default=None, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Concern
# ---------------------------------------------------------------------------


class ConcernSource(_Base):
    origin: Literal[
        "user_input",
        "tool_result",
        "memory",
        "feedback",
        "host_explicit_plan",
        "intent_alignment",
        "draft_output",
        "environment_event",
        "system_default",
        "manual_import",
        "derived",
    ]
    ref: str | None = None
    ts: datetime | None = None
    trust: float | None = Field(default=None, ge=0.0, le=1.0)


class ChainRef(_Base):
    """Optional pointer to an external on-chain / content-addressed reference.

    Schema-only placeholder: the OpenCOAT runtime never interprets this field.
    Reserved for future MOSSAI / L3 transports — see
    ``docs/07-mvp/post-m5-roadmap.md`` §6 for the rationale on landing this
    surface early. No resolver, no fetcher, no validators against
    ``network`` / ``ref`` shapes — those belong in a separate L3 RFC.
    """

    network: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    content_uri: str | None = Field(default=None, min_length=1)


class ConcernScope(_Base):
    crosscutting: bool = False
    duration: Literal["transient", "turn", "session", "long_term"] = "turn"
    joinpoint_coverage: list[str] = Field(default_factory=list)
    tenant_id: str | None = None
    agent_session_id: str | None = None


class ConcernRelation(_Base):
    target_concern_id: str
    relation_type: ConcernRelationType
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime | None = None
    #: ``runtime`` (AOP weave graph) vs ``semantic`` (cognitive lineage only).
    layer: Literal["runtime", "semantic"] = "semantic"


class DeclarePrecedence(_Base):
    kind: Literal["declare_precedence"] = "declare_precedence"
    order: list[str] = Field(
        min_length=1,
        description="Concern or advice ids, highest precedence first.",
    )


class InterTypeDeclaration(_Base):
    kind: Literal["inter_type"] = "inter_type"
    target: str
    introduces: dict[str, Any] = Field(default_factory=dict)


ConcernDeclaration = DeclarePrecedence | InterTypeDeclaration


class ConcernGraphEdge(_Base):
    """Explicit AOP graph edge (optional; mirrors DCN export)."""

    edge_type: ConcernGraphEdgeType
    from_id: str
    to_id: str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class ActivationState(_Base):
    active: bool = False
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    last_activated_at: datetime | None = None
    decay: float = Field(default=0.0, ge=0.0)


class ConcernMetrics(_Base):
    activations: int = 0
    satisfied: int = 0
    violated: int = 0
    tokens_used: int = 0


class Concern(_Base):
    id: str = Field(min_length=1)
    kind: ConcernKind = ConcernKind.CONCERN
    # ── M-E0: MAN cell-type markers (ADR-0012 Decision 4, v0.3 §3) ──────
    #: Aspect cell kind. ``"inhibitory"`` = A_reflex / InhibitoryReflex
    #: (deterministic gate, hard enforcement). ``"excitatory"`` = A_cortex /
    #: ExcitatoryNeuron (prompt-level, soft enforcement).
    neuron_type: Literal["excitatory", "inhibitory"] = "excitatory"
    #: Marks membership in the conserved core A_reflex. When ``True`` this
    #: concern is excluded from ``⇩_slow`` structural rewrites (PlasticityEngine
    #: / DCNEvolver). Implies ``neuron_type == "inhibitory"`` by convention.
    reflex: bool = False
    # ─────────────────────────────────────────────────────────────────────
    generated_type: str | None = None
    generated_tags: list[str] = Field(default_factory=list)
    name: str = Field(min_length=1)
    description: str = ""
    source: ConcernSource | None = None
    chain_ref: ChainRef | None = None
    joinpoint_selectors: list[JoinpointSelector] = Field(default_factory=list)
    pointcut: Pointcut | None = None
    advice: Advice | None = None
    weaving_policy: WeavingPolicy | None = None
    pointcuts: list[PointcutDef] = Field(default_factory=list)
    advices: list[AopAdvice] = Field(default_factory=list)
    declarations: list[ConcernDeclaration] = Field(default_factory=list)
    graph_edges: list[ConcernGraphEdge] = Field(default_factory=list)
    scope: ConcernScope | None = None
    relations: list[ConcernRelation] = Field(default_factory=list)
    activation_state: ActivationState | None = None
    lifecycle_state: LifecycleState = LifecycleState.CREATED
    metrics: ConcernMetrics = Field(default_factory=ConcernMetrics)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    schema_version: str = "0.1.0"

    @model_validator(mode="after")
    def _sync_aop_executable_shape(self) -> Concern:
        from . import aop as _aop

        synced = _aop.sync_concern_aop(self)
        if synced is self:
            return self
        for field in (
            "pointcut",
            "advice",
            "weaving_policy",
            "pointcuts",
            "advices",
            "declarations",
        ):
            object.__setattr__(self, field, getattr(synced, field))
        return self


class MetaConcern(Concern):
    kind: ConcernKind = ConcernKind.META_CONCERN
    governance_capability: GovernanceCapability


# ---------------------------------------------------------------------------
# COPR
# ---------------------------------------------------------------------------


class CoprPromptSection(_Base):
    path: str
    raw_text: str | None = None


class CoprSpan(_Base):
    id: str
    text: str
    semantic_type: str | None = None
    tokens: list[str] | None = None
    char_range: tuple[int, int] | None = None


class CoprMessage(_Base):
    id: str | None = None
    role: Literal["system", "developer", "user", "assistant", "tool", "memory", "retrieved_context"]
    raw_text: str | None = None
    sections: list[CoprPromptSection] = Field(default_factory=list)
    spans: list[CoprSpan] = Field(default_factory=list)
    structure: dict[str, Any] | None = None


class COPR(_Base):
    prompt_id: str = Field(min_length=1)
    schema_version: str = "0.1.0"
    messages: list[CoprMessage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Concern Vector
# ---------------------------------------------------------------------------


class ActiveConcern(_Base):
    concern_id: str
    activation_score: float = Field(ge=0.0, le=1.0)
    priority: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    injection_mode: str | None = None
    matched_joinpoint: str | None = None


class VectorBudget(_Base):
    max_active_concerns: int | None = Field(default=None, ge=1)
    max_injection_tokens: int | None = Field(default=None, ge=1)


class ConcernVector(_Base):
    #: One joinpoint weave run (``weave-{joinpoint.id}`` when minted by the runtime).
    weave_id: str
    agent_session_id: str | None = None
    #: Optional host dialog round correlated with this weave.
    host_round_id: str | None = None
    ts: datetime | None = None
    schema_version: str = "0.2.0"
    active_concerns: list[ActiveConcern] = Field(default_factory=list)
    budget: VectorBudget | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_turn_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("turn_id") is not None:
            data = dict(data)
            if data.get("weave_id") is None:
                data["weave_id"] = data["turn_id"]
            data.pop("turn_id", None)
        return data


# ---------------------------------------------------------------------------
# Concern Injection (output of weaving)
# ---------------------------------------------------------------------------


class Injection(_Base):
    concern_id: str
    advice_type: AdviceType | None = None
    target: str
    mode: WeavingOperation
    level: WeavingLevel | None = None
    content: str
    priority: float | None = Field(default=None, ge=0.0, le=1.0)


class InjectionTotals(_Base):
    tokens: int = 0
    concern_count: int = 0
    advice_count: int = 0


class ConcernInjection(_Base):
    weave_id: str
    agent_session_id: str | None = None
    host_round_id: str | None = None
    ts: datetime | None = None
    schema_version: str = "0.2.0"
    injections: list[Injection] = Field(default_factory=list)
    totals: InjectionTotals | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_turn_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("turn_id") is not None:
            data = dict(data)
            if data.get("weave_id") is None:
                data["weave_id"] = data["turn_id"]
            data.pop("turn_id", None)
        return data
