"""Weaving subsystem — project advice into the host's running context.

11 operations × 8 levels (v0.1 §15). The default weaver is
:class:`ConcernWeaver`; alternative weavers can subclass it and override
:meth:`build`.

M-E0: :mod:`enforcement` adds hard/soft classification for every
``WeavingOperation`` and ``AdviceType`` (ADR-0012 Decision 4).
"""

from . import enforcement
from .enforcement import (
    ADVICE_TYPE_ENFORCEMENT,
    HARD_ADVICE_TYPES,
    HARD_OPERATIONS,
    INHIBITORY_ADVICE_TYPES,
    OPERATION_ENFORCEMENT,
    AdviceTypeMeta,
    OperationMeta,
    advice_type_meta,
    operation_meta,
)
from .merge import merge_injections
from .operations import OPERATIONS
from .targets import WEAVING_TARGETS
from .weaver import ConcernWeaver

__all__ = [
    "ADVICE_TYPE_ENFORCEMENT",
    "HARD_ADVICE_TYPES",
    "HARD_OPERATIONS",
    "INHIBITORY_ADVICE_TYPES",
    "OPERATION_ENFORCEMENT",
    "OPERATIONS",
    "WEAVING_TARGETS",
    "AdviceTypeMeta",
    "ConcernWeaver",
    "OperationMeta",
    "advice_type_meta",
    "enforcement",
    "merge_injections",
    "operation_meta",
]
