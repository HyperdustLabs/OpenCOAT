"""Hermetic tests for :class:`BaiLLMClient`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from opencoat_runtime_core.ports import LLMClient
from opencoat_runtime_llm import BaiClientError, BaiLLMClient
from opencoat_runtime_llm.bai_client import BAI_DEFAULT_BASE_URL


def test_uses_bai_defaults() -> None:
    fake_OpenAI = MagicMock()
    with (
        patch.dict("os.environ", {"BAI_API_KEY": "sk-bai-test"}, clear=False),
        patch("openai.OpenAI", fake_OpenAI),
    ):
        BaiLLMClient()

    kwargs = fake_OpenAI.call_args.kwargs
    assert kwargs["api_key"] == "sk-bai-test"
    assert kwargs["base_url"] == BAI_DEFAULT_BASE_URL


def test_missing_key_raises() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("openai.OpenAI", MagicMock()),
    ):
        try:
            BaiLLMClient(api_key=None)
        except BaiClientError as exc:
            assert "BAI_API_KEY" in str(exc)
        else:
            raise AssertionError("expected BaiClientError")


def test_satisfies_llm_client_protocol() -> None:
    assert isinstance(BaiLLMClient(api_key="sk-test"), LLMClient)
