"""Catalog scan helpers for DCN evolution and daemon heartbeat workers."""

from __future__ import annotations

from opencoat_runtime_protocol import Concern


def joinpoint_names(concern: Concern) -> frozenset[str]:
    names: set[str] = set()
    if concern.pointcut is not None:
        for jp in concern.pointcut.joinpoints:
            if isinstance(jp, str) and jp:
                names.add(jp)
    for pc in concern.pointcuts:
        for jp in pc.joinpoints:
            if isinstance(jp, str) and jp:
                names.add(jp)
    return frozenset(names)


def activation_keywords(concern: Concern) -> frozenset[str]:
    keywords: set[str] = set()
    if concern.pointcut is not None and concern.pointcut.match is not None:
        raw = concern.pointcut.match.any_keywords
        if raw:
            keywords.update(k for k in raw if isinstance(k, str) and k)
    for pc in concern.pointcuts:
        if pc.match is None or not pc.match.any_keywords:
            continue
        keywords.update(k for k in pc.match.any_keywords if isinstance(k, str) and k)
    return frozenset(keywords)


__all__ = ["activation_keywords", "joinpoint_names"]
