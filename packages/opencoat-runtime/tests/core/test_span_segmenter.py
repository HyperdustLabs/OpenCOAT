"""Tests for :class:`SpanSegmenter`."""

from __future__ import annotations

from opencoat_runtime_core.copr import SpanSegmenter


def test_segments_imperative_sentence() -> None:
    spans = SpanSegmenter().segment("Never run rm -rf in shell.\n\nThanks.")
    assert spans
    assert any(s.semantic_type == "imperative" for s in spans)
    assert any("rm" in s.text for s in spans)
