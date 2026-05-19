"""Joinpoint subsystem.

Mirrors v0.1 §12: 8 levels of joinpoints, plus a catalog of well-known names.
"""

from .aliases import (
    OPENCLAW_V01_ALIASES,
    OPENCLAW_V01_MVP_JOINPOINTS,
    canonical_joinpoint_name,
    joinpoint_names_match,
)
from .catalog import JOINPOINT_CATALOG, JoinpointCatalog
from .discovery import JoinpointDiscovery
from .event_map import EVENT_TYPE_TO_JOINPOINT, joinpoint_name_for_event
from .levels import JoinpointLevel
from .model import JoinpointEvent, JoinpointSelector

__all__ = [
    "EVENT_TYPE_TO_JOINPOINT",
    "JOINPOINT_CATALOG",
    "OPENCLAW_V01_ALIASES",
    "OPENCLAW_V01_MVP_JOINPOINTS",
    "JoinpointCatalog",
    "JoinpointDiscovery",
    "JoinpointEvent",
    "JoinpointLevel",
    "JoinpointSelector",
    "canonical_joinpoint_name",
    "joinpoint_name_for_event",
    "joinpoint_names_match",
]
