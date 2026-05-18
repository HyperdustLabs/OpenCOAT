"""OpenCOAT Runtime Protocol — JSON Schemas and pydantic envelopes.

This package is the source of truth for every cross-process / cross-language
data contract used by the OpenCOAT Runtime. JSON Schemas live under
``opencoat_runtime_protocol/schemas`` and the matching pydantic models are exposed
from :mod:`opencoat_runtime_protocol.envelopes`.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from . import aop, envelopes
from .envelopes import (
    COPR,
    ActivationState,
    Advice,
    AdviceKind,
    AdviceType,
    AopAdvice,
    ChainRef,
    ClaimMatch,
    Concern,
    ConcernGraphEdge,
    ConcernGraphEdgeType,
    ConcernInjection,
    ConcernKind,
    ConcernMetrics,
    ConcernRelationType,
    ConcernVector,
    ConfidenceMatch,
    ContextPredicate,
    DeclarePrecedence,
    Injection,
    JoinpointEvent,
    JoinpointSelector,
    LifecycleState,
    MetaConcern,
    Pointcut,
    PointcutDef,
    PointcutMatch,
    RiskMatch,
    StructureMatch,
    WeavingLevel,
    WeavingOp,
    WeavingOperation,
    WeavingPolicy,
)
from .schema_loader import SCHEMA_FILES, load_schema, schema_dir, schemas

try:
    __version__ = _version("opencoat-runtime-protocol")
except PackageNotFoundError:  # editable install before metadata exists
    __version__ = "0.0.0"

SCHEMA_VERSION = "0.1.0"

__all__ = [
    "COPR",
    "SCHEMA_FILES",
    "SCHEMA_VERSION",
    "ActivationState",
    "Advice",
    "AdviceKind",
    "AdviceType",
    "AopAdvice",
    "ChainRef",
    "ClaimMatch",
    "Concern",
    "ConcernGraphEdge",
    "ConcernGraphEdgeType",
    "ConcernInjection",
    "ConcernKind",
    "ConcernMetrics",
    "ConcernRelationType",
    "ConcernVector",
    "ConfidenceMatch",
    "ContextPredicate",
    "DeclarePrecedence",
    "Injection",
    "JoinpointEvent",
    "JoinpointSelector",
    "LifecycleState",
    "MetaConcern",
    "Pointcut",
    "PointcutDef",
    "PointcutMatch",
    "RiskMatch",
    "StructureMatch",
    "WeavingLevel",
    "WeavingOp",
    "WeavingOperation",
    "WeavingPolicy",
    "aop",
    "envelopes",
    "load_schema",
    "schema_dir",
    "schemas",
]
