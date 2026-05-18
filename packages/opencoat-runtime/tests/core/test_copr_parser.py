"""Tests for :class:`CoprParser`."""

from __future__ import annotations

import pytest
from opencoat_runtime_core.copr import CoprParser
from opencoat_runtime_protocol import COPR


def test_parse_plain_string() -> None:
    copr = CoprParser().parse("hello", prompt_id="p-1")
    assert copr.prompt_id == "p-1"
    assert len(copr.messages) == 1
    assert copr.messages[0].role == "user"
    assert copr.messages[0].raw_text == "hello"


def test_parse_openai_messages_dict() -> None:
    copr = CoprParser().parse(
        {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
            ]
        },
        prompt_id="chat-1",
    )
    assert copr.prompt_id == "chat-1"
    assert [m.role for m in copr.messages] == ["system", "user"]
    assert copr.messages[1].raw_text == "Hi"


def test_parse_embedded_copr() -> None:
    inner = COPR(
        prompt_id="embedded",
        messages=[{"role": "user", "raw_text": "x"}],
    )
    copr = CoprParser().parse({"copr": inner.model_dump(mode="json")})
    assert copr.prompt_id == "embedded"


def test_parse_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="expected messages"):
        CoprParser().parse({"foo": "bar"})
