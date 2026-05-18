"""Text / chat messages → COPR parser."""

from __future__ import annotations

import uuid
from typing import Any

from opencoat_runtime_protocol import COPR
from opencoat_runtime_protocol.envelopes import CoprMessage, CoprPromptSection, CoprSpan

from .span_segmenter import SpanSegmenter

_VALID_ROLES = frozenset(
    {"system", "developer", "user", "assistant", "tool", "memory", "retrieved_context"}
)


class CoprParser:
    """Parse a raw prompt string or OpenAI-style messages into :class:`COPR`."""

    def __init__(
        self, *, segmenter: SpanSegmenter | None = None, segment_spans: bool = True
    ) -> None:
        self._segmenter = segmenter or SpanSegmenter()
        self._segment_spans = segment_spans

    def parse(self, raw: str | dict[str, Any] | list[Any], *, prompt_id: str | None = None) -> COPR:
        pid = prompt_id or f"prompt-{uuid.uuid4().hex[:12]}"
        if isinstance(raw, str):
            return COPR(
                prompt_id=pid,
                messages=[CoprMessage(role="user", raw_text=raw)],
            )
        if isinstance(raw, list):
            return COPR(prompt_id=pid, messages=self._parse_messages(raw))
        if not isinstance(raw, dict):
            raise TypeError(f"unsupported COPR input type: {type(raw)!r}")
        if "copr" in raw and isinstance(raw["copr"], dict):
            return COPR.model_validate(raw["copr"])
        if "messages" in raw:
            messages_raw = raw["messages"]
            if not isinstance(messages_raw, list):
                raise TypeError("messages must be a list")
            return COPR(
                prompt_id=str(raw.get("prompt_id") or pid),
                messages=self._parse_messages(messages_raw),
            )
        if "role" in raw:
            return COPR(prompt_id=pid, messages=[self._parse_message(raw)])
        raise ValueError("expected messages list, copr object, or role/content message dict")

    def _parse_messages(self, items: list[Any]) -> list[CoprMessage]:
        out: list[CoprMessage] = []
        for item in items:
            if not isinstance(item, dict):
                raise TypeError(f"each message must be a dict, got {type(item)!r}")
            out.append(self._parse_message(item))
        return out

    def _parse_message(self, item: dict[str, Any]) -> CoprMessage:
        role_raw = str(item.get("role", "user"))
        role = role_raw if role_raw in _VALID_ROLES else "user"
        text = _message_text(item)
        sections_raw = item.get("sections")
        sections: list[CoprPromptSection] = []
        if isinstance(sections_raw, list):
            for sec in sections_raw:
                if not isinstance(sec, dict):
                    continue
                path = sec.get("path")
                if not isinstance(path, str) or not path:
                    continue
                sections.append(
                    CoprPromptSection(
                        path=path,
                        raw_text=sec.get("raw_text")
                        if isinstance(sec.get("raw_text"), str)
                        else None,
                    )
                )
        spans = []
        if isinstance(item.get("spans"), list):
            for raw_span in item["spans"]:
                if isinstance(raw_span, dict) and raw_span.get("text"):
                    spans.append(CoprSpan.model_validate(raw_span))
        elif self._segment_spans and text:
            spans = self._segmenter.segment(text)

        return CoprMessage(
            id=str(item["id"]) if item.get("id") is not None else None,
            role=role,
            raw_text=text,
            sections=sections,
            spans=spans,
            structure=item.get("structure") if isinstance(item.get("structure"), dict) else None,
        )


def _message_text(item: dict[str, Any]) -> str | None:
    for key in ("raw_text", "text", "content"):
        raw = item.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return None
