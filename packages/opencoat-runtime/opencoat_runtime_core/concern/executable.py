"""Executable view of concerns for matcher / weaver (AOP-normalized)."""

from __future__ import annotations

from opencoat_runtime_protocol.aop import (
    has_executable_pointcut,
    primary_advice,
    primary_pointcut,
    primary_weaving,
)

__all__ = [
    "has_executable_pointcut",
    "primary_advice",
    "primary_pointcut",
    "primary_weaving",
]
