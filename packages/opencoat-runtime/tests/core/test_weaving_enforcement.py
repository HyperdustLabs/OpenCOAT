"""M-E0 acceptance tests for weaving enforcement classification.

Verifies:
1. Every WeavingOperation is in the classification table (full coverage).
2. Every AdviceType is in the classification table (full coverage).
3. Hard / soft split is correct for operations and advice types.
4. Convenience sets (HARD_OPERATIONS, HARD_ADVICE_TYPES, INHIBITORY_ADVICE_TYPES)
   are consistent with the full tables.
5. A_reflex members (reflex=True concerns) are excluded from DCNEvolver
   ⇩_slow rewrites (merge and archive).

References: ADR-0012 Decision 4, v0.3 §3, MAN §1.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opencoat_runtime_core.dcn.evolution import DCNEvolver
from opencoat_runtime_core.weaving.enforcement import (
    ADVICE_TYPE_ENFORCEMENT,
    HARD_ADVICE_TYPES,
    HARD_OPERATIONS,
    INHIBITORY_ADVICE_TYPES,
    OPERATION_ENFORCEMENT,
    advice_type_meta,
    operation_meta,
)
from opencoat_runtime_protocol import (
    ActivationState,
    Advice,
    AdviceType,
    Concern,
    LifecycleState,
    Pointcut,
    WeavingLevel,
    WeavingOperation,
    WeavingPolicy,
)
from opencoat_runtime_protocol.envelopes import PointcutMatch
from opencoat_runtime_storage.memory import MemoryConcernStore, MemoryDCNStore

_NOW = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concern(
    cid: str,
    *,
    keywords: list[str],
    score: float = 0.6,
    decay: float = 0.0,
    lifecycle: str = LifecycleState.ACTIVE.value,
    reflex: bool = False,
    neuron_type: str = "excitatory",
) -> Concern:
    return Concern(
        id=cid,
        name=cid,
        description=cid,
        lifecycle_state=lifecycle,
        reflex=reflex,
        neuron_type=neuron_type,  # type: ignore[arg-type]
        activation_state=ActivationState(score=score, decay=decay, active=True),
        pointcut=Pointcut(
            joinpoints=["before_tool_call"],
            match=PointcutMatch(any_keywords=keywords),
        ),
        advice=Advice(type=AdviceType.TOOL_GUARD, content="block unsafe tools"),
        weaving_policy=WeavingPolicy(
            mode=WeavingOperation.BLOCK,
            level=WeavingLevel.TOOL_LEVEL,
            target="tool_call.arguments.*",
            priority=0.9,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Full coverage — WeavingOperation
# ---------------------------------------------------------------------------


class TestOperationCoverage:
    def test_all_operations_classified(self) -> None:
        """Every WeavingOperation must appear in OPERATION_ENFORCEMENT."""
        missing = [op for op in WeavingOperation if op not in OPERATION_ENFORCEMENT]
        assert missing == [], f"Unclassified WeavingOperation(s): {missing}"

    def test_table_has_no_extra_entries(self) -> None:
        """Table must not contain values outside the enum."""
        valid = set(WeavingOperation)
        extra = [op for op in OPERATION_ENFORCEMENT if op not in valid]
        assert extra == []

    def test_operation_meta_lookup(self) -> None:
        for op in WeavingOperation:
            meta = operation_meta(op)
            assert meta.operation == op
            assert meta.enforcement in ("hard", "soft")
            assert meta.fail_mode in ("deny", "allow")

    def test_hard_operations_are_block_and_verify(self) -> None:
        assert {WeavingOperation.BLOCK, WeavingOperation.VERIFY} == HARD_OPERATIONS

    def test_soft_operations_fail_open(self) -> None:
        for op in WeavingOperation:
            meta = operation_meta(op)
            if meta.enforcement == "soft":
                assert meta.fail_mode == "allow", (
                    f"{op}: soft op must be fail_mode=allow, got {meta.fail_mode}"
                )

    def test_hard_operations_fail_closed(self) -> None:
        for op in HARD_OPERATIONS:
            meta = operation_meta(op)
            assert meta.fail_mode == "deny", (
                f"{op}: hard op must be fail_mode=deny, got {meta.fail_mode}"
            )


# ---------------------------------------------------------------------------
# 2. Full coverage — AdviceType
# ---------------------------------------------------------------------------


class TestAdviceTypeCoverage:
    def test_all_advice_types_classified(self) -> None:
        """Every AdviceType must appear in ADVICE_TYPE_ENFORCEMENT."""
        missing = [at for at in AdviceType if at not in ADVICE_TYPE_ENFORCEMENT]
        assert missing == [], f"Unclassified AdviceType(s): {missing}"

    def test_table_has_no_extra_entries(self) -> None:
        valid = set(AdviceType)
        extra = [at for at in ADVICE_TYPE_ENFORCEMENT if at not in valid]
        assert extra == []

    def test_advice_type_meta_lookup(self) -> None:
        for at in AdviceType:
            meta = advice_type_meta(at)
            assert meta.advice_type == at
            assert meta.enforcement in ("hard", "soft")
            assert meta.fail_mode in ("deny", "allow")
            assert meta.neuron_type in ("inhibitory", "excitatory")

    def test_hard_advice_types_are_guards_and_verification(self) -> None:
        assert {
            AdviceType.TOOL_GUARD,
            AdviceType.MEMORY_WRITE_GUARD,
            AdviceType.VERIFICATION_RULE,
        } == HARD_ADVICE_TYPES

    def test_inhibitory_equals_hard_advice_types(self) -> None:
        """All inhibitory advice types must be hard, and vice-versa."""
        assert INHIBITORY_ADVICE_TYPES == HARD_ADVICE_TYPES

    def test_soft_advice_types_fail_open(self) -> None:
        for at in AdviceType:
            meta = advice_type_meta(at)
            if meta.enforcement == "soft":
                assert meta.fail_mode == "allow"
                assert meta.neuron_type == "excitatory"

    def test_hard_advice_types_fail_closed_inhibitory(self) -> None:
        for at in HARD_ADVICE_TYPES:
            meta = advice_type_meta(at)
            assert meta.fail_mode == "deny"
            assert meta.neuron_type == "inhibitory"


# ---------------------------------------------------------------------------
# 3. Concern model — neuron_type and reflex fields
# ---------------------------------------------------------------------------


class TestConcernFields:
    def test_defaults(self) -> None:
        c = Concern(id="c1", name="test concern")
        assert c.neuron_type == "excitatory"
        assert c.reflex is False

    def test_inhibitory_reflex_concern(self) -> None:
        c = Concern(
            id="reflex-1",
            name="tool guard",
            neuron_type="inhibitory",
            reflex=True,
        )
        assert c.neuron_type == "inhibitory"
        assert c.reflex is True

    def test_model_copy_preserves_fields(self) -> None:
        c = Concern(id="c2", name="base", neuron_type="inhibitory", reflex=True)
        c2 = c.model_copy(update={"name": "updated"})
        assert c2.reflex is True
        assert c2.neuron_type == "inhibitory"

    def test_serialisation_roundtrip(self) -> None:
        c = Concern(id="c3", name="rt", neuron_type="inhibitory", reflex=True)
        data = c.model_dump()
        assert data["neuron_type"] == "inhibitory"
        assert data["reflex"] is True
        c2 = Concern.model_validate(data)
        assert c2.neuron_type == "inhibitory"
        assert c2.reflex is True


# ---------------------------------------------------------------------------
# 4. DCNEvolver — A_reflex excluded from ⇩_slow (M-E0 invariant)
# ---------------------------------------------------------------------------


class TestReflexExcludedFromEvolution:
    def _make_evolver(self, store: MemoryConcernStore, dcn: MemoryDCNStore) -> DCNEvolver:
        return DCNEvolver(
            concern_store=store,
            dcn_store=dcn,
            merge_min_keyword_overlap=2,
        )

    def test_reflex_concern_not_merged(self) -> None:
        """A reflex concern must survive even when it overlaps keywords with another."""
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern("reflex-a", keywords=["tool", "guard"], reflex=True, neuron_type="inhibitory")
        )
        store.upsert(_concern("soft-b", keywords=["tool", "guard"], score=0.3))
        result = self._make_evolver(store, dcn).run(_NOW)
        assert result.merged == 0, "reflex concern must not be merged"
        assert store.get("reflex-a") is not None
        assert store.get("reflex-a").lifecycle_state not in {
            LifecycleState.MERGED.value,
            LifecycleState.ARCHIVED.value,
        }

    def test_reflex_concern_not_archived_when_cold(self) -> None:
        """A cold weakened reflex concern must not be archived by ⇩_slow."""
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern(
                "reflex-cold",
                keywords=["memory"],
                score=0.05,
                decay=0.95,
                lifecycle=LifecycleState.WEAKENED.value,
                reflex=True,
                neuron_type="inhibitory",
            )
        )
        result = self._make_evolver(store, dcn).run(_NOW)
        assert result.archived == 0, "reflex concern must not be archived"
        c = store.get("reflex-cold")
        assert c is not None
        assert c.lifecycle_state == LifecycleState.WEAKENED.value

    def test_non_reflex_concern_still_merged(self) -> None:
        """Non-reflex concerns are still subject to ⇩_slow as before."""
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(_concern("dup-a", keywords=["NVDA", "分析"], score=0.8))
        store.upsert(_concern("dup-b", keywords=["NVDA", "分析"], score=0.3))
        result = self._make_evolver(store, dcn).run(_NOW)
        assert result.merged == 1

    def test_non_reflex_concern_still_archived(self) -> None:
        """Non-reflex cold weakened concerns are still archived."""
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern(
                "soft-cold",
                keywords=["x"],
                score=0.05,
                decay=0.95,
                lifecycle=LifecycleState.WEAKENED.value,
            )
        )
        result = self._make_evolver(store, dcn).run(_NOW)
        assert result.archived == 1

    def test_two_reflex_concerns_both_survive(self) -> None:
        """Two reflex concerns with identical keywords must both survive."""
        store = MemoryConcernStore()
        dcn = MemoryDCNStore()
        store.upsert(
            _concern("r1", keywords=["tool", "safety"], reflex=True, neuron_type="inhibitory")
        )
        store.upsert(
            _concern("r2", keywords=["tool", "safety"], reflex=True, neuron_type="inhibitory")
        )
        result = self._make_evolver(store, dcn).run(_NOW)
        assert result.merged == 0
        assert store.get("r1") is not None
        assert store.get("r2") is not None
