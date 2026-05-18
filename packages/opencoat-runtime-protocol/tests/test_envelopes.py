"""Round-trip tests for pydantic envelopes ↔ JSON Schemas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from jsonschema import Draft202012Validator
from opencoat_runtime_protocol import (
    COPR,
    SCHEMA_FILES,
    Advice,
    AdviceType,
    ChainRef,
    Concern,
    ConcernInjection,
    ConcernKind,
    ConcernRelationType,
    ConcernVector,
    Injection,
    JoinpointEvent,
    JoinpointSelector,
    LifecycleState,
    MetaConcern,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
    load_schema,
)
from opencoat_runtime_protocol.envelopes import (
    ActiveConcern,
    ConcernRelation,
    ConcernScope,
    ConcernSource,
    ContextPredicate,
    CoprMessage,
    CoprSpan,
    GovernanceCapability,
    PointcutMatch,
    RiskMatch,
)
from referencing import Registry, Resource


def _registry() -> Registry:
    registry: Registry = Registry()
    for name in SCHEMA_FILES:
        schema = load_schema(name)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(uri=name, resource=resource)
        if schema.get("$id"):
            registry = registry.with_resource(uri=schema["$id"], resource=resource)
    return registry


def _validate(schema_file: str, payload: dict) -> None:
    """Validate ``payload`` against ``schema_file`` using cross-file refs."""
    registry = _registry()
    validator = Draft202012Validator(load_schema(schema_file), registry=registry)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)


def test_concern_minimal() -> None:
    c = Concern(id="c-1", name="user wants concise answers")
    assert c.kind == ConcernKind.CONCERN.value
    assert c.lifecycle_state == LifecycleState.CREATED.value
    _validate("concern.schema.json", c.model_dump(mode="json", exclude_none=True))


def test_concern_full_roundtrip() -> None:
    now = datetime(2026, 5, 7, 12, 0, 0, tzinfo=UTC)
    c = Concern(
        id="c-42",
        kind=ConcernKind.CONCERN,
        generated_type="evidence_based_answer",
        generated_tags=["accuracy", "evidence"],
        name="answers must cite evidence",
        description="The agent must cite evidence rather than make up facts.",
        source=ConcernSource(origin="user_input", ts=now, trust=0.9),
        joinpoint_selectors=[
            JoinpointSelector(level="lifecycle", path="before_response"),
        ],
        pointcut=Pointcut(
            joinpoints=["before_response"],
            match=PointcutMatch(
                semantic_intent="evidence_required",
                any_keywords=["confirm", "evidence", "cite"],
                risk=RiskMatch(op=">=", level="medium"),
            ),
        ),
        advice=Advice(
            type=AdviceType.VERIFICATION_RULE,
            content="Verify every factual claim has an explicit source.",
        ),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.INSERT,
            level=WeavingLevel.VERIFICATION_LEVEL,
            target="runtime_prompt.verification_rules",
            priority=0.85,
        ),
        scope=ConcernScope(
            crosscutting=True,
            duration="long_term",
            joinpoint_coverage=["before_reasoning", "before_response", "after_response"],
        ),
        relations=[
            ConcernRelation(
                target_concern_id="c-43",
                relation_type=ConcernRelationType.VERIFIES,
                weight=0.8,
            )
        ],
        lifecycle_state=LifecycleState.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    payload = c.model_dump(mode="json", exclude_none=True)
    _validate("concern.schema.json", payload)
    # Round-trip
    again = Concern.model_validate(payload)
    assert again.id == c.id
    assert again.advice and again.advice.type == AdviceType.VERIFICATION_RULE.value


def test_meta_concern_requires_governance_capability() -> None:
    m = MetaConcern(
        id="mc-1",
        name="budget control",
        governance_capability=GovernanceCapability.BUDGET_CONTROL,
    )
    payload = m.model_dump(mode="json", exclude_none=True)
    _validate("meta_concern.schema.json", payload)
    with pytest.raises(Exception):
        MetaConcern(id="mc-2", name="bad")  # missing governance_capability


def test_joinpoint_event() -> None:
    jp = JoinpointEvent(
        id="jp-1",
        level=1,
        name="before_response",
        host="openclaw",
        agent_session_id="s-1",
        host_round_id="round-1",
        ts=datetime.now(UTC),
        payload={"kind": "lifecycle", "stage": "before_response", "data": {}},
    )
    _validate("joinpoint.schema.json", jp.model_dump(mode="json", exclude_none=True))


def test_pointcut_with_predicates() -> None:
    pc = Pointcut(
        joinpoints=["tool_call.arguments"],
        match=PointcutMatch(
            semantic_intent="high_risk_decision",
            any_keywords=["all in", "guaranteed"],
        ),
        context_predicates=[
            ContextPredicate(key="risk_level", op=">=", value="medium"),
        ],
    )
    _validate("pointcut.schema.json", pc.model_dump(mode="json", exclude_none=True))


def test_copr_tree() -> None:
    copr = COPR(
        prompt_id="p-1",
        messages=[
            CoprMessage(
                role="user",
                raw_text="Should I go all in on this stock?",
                spans=[
                    CoprSpan(
                        id="s-1",
                        text="all in",
                        semantic_type="high_risk_action_request",
                        tokens=["all", "in"],
                    )
                ],
            ),
        ],
    )
    _validate("copr.schema.json", copr.model_dump(mode="json", exclude_none=True))


def test_concern_vector_and_injection_roundtrip() -> None:
    vec = ConcernVector(
        weave_id="t-1",
        active_concerns=[
            ActiveConcern(
                concern_id="c-1",
                activation_score=0.92,
                priority=0.85,
                injection_mode="reasoning_guidance",
            )
        ],
    )
    _validate("concern_vector.schema.json", vec.model_dump(mode="json", exclude_none=True))

    inj = ConcernInjection(
        weave_id="t-1",
        injections=[
            Injection(
                concern_id="c-1",
                advice_type=AdviceType.REASONING_GUIDANCE,
                target="runtime_prompt.reasoning_guidance",
                mode=WeavingOperation.INSERT,
                level=WeavingLevel.PROMPT_LEVEL,
                content="Identify the user's true concern, not the surface question.",
                priority=0.82,
            )
        ],
    )
    _validate("concern_injection.schema.json", inj.model_dump(mode="json", exclude_none=True))


def test_extra_fields_rejected_by_pydantic() -> None:
    """Pydantic envelopes are the strict source of truth for extra-field policy."""
    with pytest.raises(Exception):
        Concern(id="c-x", name="bad", weird_unknown_field=1)  # type: ignore[call-arg]


class TestConcernChainRef:
    """``Concern.chain_ref`` — schema-only L3 placeholder (post-M5 roadmap §6).

    The runtime never interprets this field; these tests pin the *surface*
    so future MOSSAI / external callers can populate it without schema
    churn. No resolver / fetcher is in scope.
    """

    def test_omitted_by_default(self) -> None:
        c = Concern(id="c-no-chain", name="no chain ref")
        assert c.chain_ref is None
        payload = c.model_dump(mode="json", exclude_none=True)
        assert "chain_ref" not in payload
        _validate("concern.schema.json", payload)

    def test_minimal_chain_ref_roundtrips(self) -> None:
        c = Concern(
            id="c-with-chain",
            name="anchored concern",
            chain_ref=ChainRef(network="evm:1", ref="0xabc"),
        )
        payload = c.model_dump(mode="json", exclude_none=True)
        _validate("concern.schema.json", payload)
        assert payload["chain_ref"] == {"network": "evm:1", "ref": "0xabc"}
        again = Concern.model_validate(payload)
        assert again.chain_ref is not None
        assert again.chain_ref.network == "evm:1"
        assert again.chain_ref.ref == "0xabc"
        assert again.chain_ref.content_uri is None

    def test_full_chain_ref_with_content_uri(self) -> None:
        c = Concern(
            id="c-ipfs",
            name="ipfs-anchored concern",
            chain_ref=ChainRef(
                network="evm:1",
                ref="0x" + "a" * 64,
                content_uri="ipfs://bafy.../concern.json",
            ),
        )
        payload = c.model_dump(mode="json", exclude_none=True)
        _validate("concern.schema.json", payload)
        assert payload["chain_ref"]["content_uri"] == "ipfs://bafy.../concern.json"

    def test_chain_ref_required_fields_via_schema(self) -> None:
        """Schema must reject a chain_ref missing ``network`` or ``ref``."""
        bad = {
            "id": "c-bad",
            "kind": "concern",
            "name": "missing ref",
            "schema_version": "0.1.0",
            "chain_ref": {"network": "evm:1"},
        }
        with pytest.raises(AssertionError):
            _validate("concern.schema.json", bad)

    def test_chain_ref_required_fields_via_pydantic(self) -> None:
        with pytest.raises(Exception):
            ChainRef(network="evm:1")  # type: ignore[call-arg]
        with pytest.raises(Exception):
            ChainRef(ref="0xabc")  # type: ignore[call-arg]

    def test_chain_ref_rejects_extra_fields(self) -> None:
        """``ChainRef`` follows the package-wide ``extra='forbid'`` policy."""
        with pytest.raises(Exception):
            ChainRef(network="evm:1", ref="0xabc", chain_id=1)  # type: ignore[call-arg]

    def test_chain_ref_rejects_empty_strings(self) -> None:
        with pytest.raises(Exception):
            ChainRef(network="", ref="0xabc")
        with pytest.raises(Exception):
            ChainRef(network="evm:1", ref="")

    def test_meta_concern_inherits_chain_ref(self) -> None:
        """``MetaConcern`` extends ``Concern`` → ``chain_ref`` is available."""
        from opencoat_runtime_protocol.envelopes import GovernanceCapability

        m = MetaConcern(
            id="mc-anchor",
            name="anchored governance",
            governance_capability=GovernanceCapability.LIFECYCLE_CONTROL,
            chain_ref=ChainRef(network="evm:1", ref="0xdef"),
        )
        payload = m.model_dump(mode="json", exclude_none=True)
        _validate("meta_concern.schema.json", payload)
        assert payload["chain_ref"] == {"network": "evm:1", "ref": "0xdef"}
