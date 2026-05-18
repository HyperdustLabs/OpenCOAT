"""Lightweight tokenizer for COPR (whitespace + punctuation split)."""

from __future__ import annotations

import re

_TOKEN_SPLIT = re.compile(r"[\s]+|(?<=[.,;:!?])")


class CoprTokenizer:
    def tokenize(self, text: str) -> list[str]:
        if not text.strip():
            return []
        parts = _TOKEN_SPLIT.split(text.strip())
        return [p for p in parts if p]

    def count_tokens(self, text: str) -> int:
        return len(self.tokenize(text))
