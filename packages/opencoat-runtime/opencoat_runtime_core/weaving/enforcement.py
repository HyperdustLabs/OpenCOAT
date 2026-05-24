"""Enforcement classification for WeavingOperation and AdviceType (M-E0).

Maps every op/advice-type to:
  - enforcement: "hard" | "soft"
  - fail_mode:   "deny" | "allow"
  - neuron_type: "inhibitory" | "excitatory"   (AdviceType only)

Design grounding
----------------
- Hard ops execute at in-proc synchronous gate points (A_reflex / InhibitoryReflex).
  A missing or erring hard gate defaults to *deny* (fail-closed).
- Soft ops are prompt-level conditionings bounded by LLM instruction-following.
  A missing soft aspect defaults to *allow* (fail-open).
- ``neuron_type`` classifies the aspect cell kind from v0.3 §3.

References: ADR-0012 Decision 4, v0.3 §3.2/§3.3, MAN §1/§2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from opencoat_runtime_protocol import AdviceType, WeavingOperation

EnforcementClass = Literal["hard", "soft"]
FailMode = Literal["deny", "allow"]
NeuronType = Literal["inhibitory", "excitatory"]


@dataclass(frozen=True)
class OperationMeta:
    """Enforcement metadata for a single :class:`WeavingOperation`."""

    operation: WeavingOperation
    enforcement: EnforcementClass
    fail_mode: FailMode


@dataclass(frozen=True)
class AdviceTypeMeta:
    """Enforcement metadata for a single :class:`AdviceType`."""

    advice_type: AdviceType
    enforcement: EnforcementClass
    fail_mode: FailMode
    neuron_type: NeuronType


# ---------------------------------------------------------------------------
# WeavingOperation classification
#
# Deterministic gate ops (used by A_reflex / InhibitoryReflex at effect
# boundaries) → hard / deny.
# All prompt-level conditioning ops → soft / allow.
# ---------------------------------------------------------------------------

OPERATION_ENFORCEMENT: Final[dict[WeavingOperation, OperationMeta]] = {
    # ── hard ─────────────────────────────────────────────────────────────
    WeavingOperation.BLOCK: OperationMeta(
        operation=WeavingOperation.BLOCK,
        enforcement="hard",
        fail_mode="deny",
    ),
    WeavingOperation.VERIFY: OperationMeta(
        operation=WeavingOperation.VERIFY,
        enforcement="hard",
        fail_mode="deny",
    ),
    # ── soft ─────────────────────────────────────────────────────────────
    WeavingOperation.INSERT: OperationMeta(
        operation=WeavingOperation.INSERT,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.REPLACE: OperationMeta(
        operation=WeavingOperation.REPLACE,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.SUPPRESS: OperationMeta(
        operation=WeavingOperation.SUPPRESS,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.ANNOTATE: OperationMeta(
        operation=WeavingOperation.ANNOTATE,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.WARN: OperationMeta(
        operation=WeavingOperation.WARN,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.REWRITE: OperationMeta(
        operation=WeavingOperation.REWRITE,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.DEFER: OperationMeta(
        operation=WeavingOperation.DEFER,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.ESCALATE: OperationMeta(
        operation=WeavingOperation.ESCALATE,
        enforcement="soft",
        fail_mode="allow",
    ),
    WeavingOperation.COMPRESS: OperationMeta(
        operation=WeavingOperation.COMPRESS,
        enforcement="soft",
        fail_mode="allow",
    ),
}

# ---------------------------------------------------------------------------
# AdviceType classification
#
# TOOL_GUARD / MEMORY_WRITE_GUARD / VERIFICATION_RULE are the A_reflex
# members in the initial conserved core — they map to InhibitoryReflex cell
# type (hard, fail-closed).  All other advice types are ExcitatoryNeuron
# (soft, fail-open).
# ---------------------------------------------------------------------------

ADVICE_TYPE_ENFORCEMENT: Final[dict[AdviceType, AdviceTypeMeta]] = {
    # ── inhibitory / hard ────────────────────────────────────────────────
    AdviceType.TOOL_GUARD: AdviceTypeMeta(
        advice_type=AdviceType.TOOL_GUARD,
        enforcement="hard",
        fail_mode="deny",
        neuron_type="inhibitory",
    ),
    AdviceType.MEMORY_WRITE_GUARD: AdviceTypeMeta(
        advice_type=AdviceType.MEMORY_WRITE_GUARD,
        enforcement="hard",
        fail_mode="deny",
        neuron_type="inhibitory",
    ),
    AdviceType.VERIFICATION_RULE: AdviceTypeMeta(
        advice_type=AdviceType.VERIFICATION_RULE,
        enforcement="hard",
        fail_mode="deny",
        neuron_type="inhibitory",
    ),
    # ── excitatory / soft ────────────────────────────────────────────────
    AdviceType.REASONING_GUIDANCE: AdviceTypeMeta(
        advice_type=AdviceType.REASONING_GUIDANCE,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.PLANNING_GUIDANCE: AdviceTypeMeta(
        advice_type=AdviceType.PLANNING_GUIDANCE,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.DECISION_GUIDANCE: AdviceTypeMeta(
        advice_type=AdviceType.DECISION_GUIDANCE,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.RESPONSE_REQUIREMENT: AdviceTypeMeta(
        advice_type=AdviceType.RESPONSE_REQUIREMENT,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.REFLECTION_PROMPT: AdviceTypeMeta(
        advice_type=AdviceType.REFLECTION_PROMPT,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.REWRITE_GUIDANCE: AdviceTypeMeta(
        advice_type=AdviceType.REWRITE_GUIDANCE,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.SUPPRESS_INSTRUCTION: AdviceTypeMeta(
        advice_type=AdviceType.SUPPRESS_INSTRUCTION,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
    AdviceType.ESCALATION_NOTICE: AdviceTypeMeta(
        advice_type=AdviceType.ESCALATION_NOTICE,
        enforcement="soft",
        fail_mode="allow",
        neuron_type="excitatory",
    ),
}

# Convenience sets for fast membership checks
HARD_OPERATIONS: Final[frozenset[WeavingOperation]] = frozenset(
    op for op, meta in OPERATION_ENFORCEMENT.items() if meta.enforcement == "hard"
)
HARD_ADVICE_TYPES: Final[frozenset[AdviceType]] = frozenset(
    at for at, meta in ADVICE_TYPE_ENFORCEMENT.items() if meta.enforcement == "hard"
)
INHIBITORY_ADVICE_TYPES: Final[frozenset[AdviceType]] = frozenset(
    at for at, meta in ADVICE_TYPE_ENFORCEMENT.items() if meta.neuron_type == "inhibitory"
)


def operation_meta(op: WeavingOperation) -> OperationMeta:
    """Return the :class:`OperationMeta` for *op*.

    Raises :exc:`KeyError` if *op* is not in the classification table —
    this should never happen for valid enum members; the test suite asserts
    full coverage.
    """
    return OPERATION_ENFORCEMENT[op]


def advice_type_meta(at: AdviceType) -> AdviceTypeMeta:
    """Return the :class:`AdviceTypeMeta` for *at*.

    Raises :exc:`KeyError` if *at* is not in the classification table.
    """
    return ADVICE_TYPE_ENFORCEMENT[at]


__all__ = [
    "ADVICE_TYPE_ENFORCEMENT",
    "HARD_ADVICE_TYPES",
    "HARD_OPERATIONS",
    "INHIBITORY_ADVICE_TYPES",
    "OPERATION_ENFORCEMENT",
    "AdviceTypeMeta",
    "EnforcementClass",
    "FailMode",
    "NeuronType",
    "OperationMeta",
    "advice_type_meta",
    "operation_meta",
]
