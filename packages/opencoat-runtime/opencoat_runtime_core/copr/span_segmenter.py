"""Span segmenter — slice message text into semantic spans."""

from __future__ import annotations

import re
import uuid

from opencoat_runtime_protocol.envelopes import CoprSpan

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_IMPERATIVE = re.compile(
    r"^\s*(?:never|do not|don't|must not|always|ensure|avoid)\b",
    re.IGNORECASE,
)


class SpanSegmenter:
    """Heuristic paragraph / sentence segmentation (no LLM)."""

    def segment(self, raw_text: str) -> list[CoprSpan]:
        text = raw_text.strip()
        if not text:
            return []
        spans: list[CoprSpan] = []
        cursor = 0
        for para in _PARAGRAPH_SPLIT.split(text):
            chunk = para.strip()
            if not chunk:
                continue
            if len(chunk) < 200:
                spans.append(_make_span(chunk, cursor, cursor + len(chunk)))
                cursor += len(chunk) + 1
                continue
            for sentence in _SENTENCE_SPLIT.split(chunk):
                sent = sentence.strip()
                if not sent:
                    continue
                start = text.find(sent, cursor)
                if start < 0:
                    start = cursor
                end = start + len(sent)
                spans.append(_make_span(sent, start, end))
                cursor = end
        return spans


def _make_span(text: str, start: int, end: int) -> CoprSpan:
    semantic = "imperative" if _IMPERATIVE.search(text) else "sentence"
    return CoprSpan(
        id=f"span-{uuid.uuid4().hex[:10]}",
        text=text,
        semantic_type=semantic,
        char_range=(start, end),
    )
