"""Weaving subsystem — project advice into the host's running context.

11 operations × 8 levels (v0.1 §15). The default weaver is
:class:`ConcernWeaver`; alternative weavers can subclass it and override
:meth:`build`.
"""

from .merge import merge_injections
from .operations import OPERATIONS
from .targets import WEAVING_TARGETS
from .weaver import ConcernWeaver

__all__ = ["OPERATIONS", "WEAVING_TARGETS", "ConcernWeaver", "merge_injections"]
