"""B.AI :class:`LLMClient` adapter (OpenAI-compatible).

Uses the B.AI chat completions API documented at https://docs.b.ai/llmservice/api/
(Base URL ``https://api.b.ai/v1``, auth via ``BAI_API_KEY`` or Bearer token).

The upstream surface matches OpenAI's ``/v1/chat/completions``, so this adapter
subclasses :class:`OpenAILLMClient` and only changes default endpoint and
credential resolution.
"""

from __future__ import annotations

import os

from .openai_client import OpenAIClientError, OpenAILLMClient

BAI_DEFAULT_BASE_URL = "https://api.b.ai/v1"
BAI_DEFAULT_MODEL = "gpt-5.2"

# Re-export for callers that want a provider-specific error type.
BaiClientError = OpenAIClientError


class BaiLLMClient(OpenAILLMClient):
    """OpenAI-compatible client for `B.AI <https://docs.b.ai/llmservice/api/>`_."""

    DEFAULT_MODEL = BAI_DEFAULT_MODEL

    def __init__(
        self,
        *,
        model: str = BAI_DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        timeout_seconds: float = 20.0,
        default_temperature: float | None = 0.0,
        default_max_tokens: int | None = None,
        score_max_tokens: int | None = OpenAILLMClient.DEFAULT_SCORE_MAX_TOKENS,
    ) -> None:
        resolved_key = api_key if api_key is not None else os.environ.get("BAI_API_KEY")
        if not resolved_key:
            raise BaiClientError(
                "BAI_API_KEY is not set and no api_key was passed. "
                "Pass api_key=... explicitly or set the BAI_API_KEY environment variable."
            )
        resolved_base = (
            base_url if base_url is not None else os.environ.get("BAI_BASE_URL")
        ) or BAI_DEFAULT_BASE_URL
        super().__init__(
            model=model,
            api_key=resolved_key,
            base_url=resolved_base,
            organization=organization,
            project=project,
            timeout_seconds=timeout_seconds,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
            score_max_tokens=score_max_tokens,
        )


__all__ = ["BAI_DEFAULT_BASE_URL", "BAI_DEFAULT_MODEL", "BaiClientError", "BaiLLMClient"]
