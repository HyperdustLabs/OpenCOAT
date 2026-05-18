"""LLM / Embedder clients.

Real providers (OpenAI, Anthropic, Azure, Ollama) live in this package.
Each is loaded lazily so importing :mod:`opencoat_runtime_llm` does not pull
in the upstream SDK — that only happens when a host actually constructs
the matching client. Users install the provider they want via the
matching optional extra::

    pip install opencoat-runtime-llm[openai]
    pip install opencoat-runtime-llm[anthropic]
    pip install opencoat-runtime-llm[azure]   # alias for the openai extra

The deterministic in-process stub used by tests + the M1 example lives
in :mod:`opencoat_runtime_core.llm` and is re-exported below for the
``from opencoat_runtime_llm import StubLLMClient`` import path that
predates the split.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import TYPE_CHECKING, Any

from .stub_client import StubLLMClient

try:
    __version__ = _version("opencoat-runtime")
except PackageNotFoundError:
    __version__ = "0.0.0"


# Lazy attribute access keeps the SDK import out of module load time.
# ``from opencoat_runtime_llm import OpenAILLMClient`` works only when the
# matching extra is installed; otherwise the import inside the adapter
# raises the provider-specific error with a fix-it-yourself message.
_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "BaiLLMClient": (".bai_client", "BaiLLMClient"),
    "BaiClientError": (".bai_client", "BaiClientError"),
    "BAI_DEFAULT_BASE_URL": (".bai_client", "BAI_DEFAULT_BASE_URL"),
    "BAI_DEFAULT_MODEL": (".bai_client", "BAI_DEFAULT_MODEL"),
    "OpenAILLMClient": (".openai_client", "OpenAILLMClient"),
    "OpenAIClientError": (".openai_client", "OpenAIClientError"),
    "AnthropicLLMClient": (".anthropic_client", "AnthropicLLMClient"),
    "AnthropicClientError": (".anthropic_client", "AnthropicClientError"),
    "AzureOpenAILLMClient": (".azure_openai_client", "AzureOpenAILLMClient"),
    "AzureOpenAIClientError": (".azure_openai_client", "AzureOpenAIClientError"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = target
    from importlib import import_module

    module = import_module(module_path, package=__name__)
    return getattr(module, attr)


if TYPE_CHECKING:  # pragma: no cover — re-exported for static analysis only
    from .anthropic_client import AnthropicClientError, AnthropicLLMClient
    from .azure_openai_client import AzureOpenAIClientError, AzureOpenAILLMClient
    from .bai_client import BAI_DEFAULT_BASE_URL, BAI_DEFAULT_MODEL, BaiClientError, BaiLLMClient
    from .openai_client import OpenAIClientError, OpenAILLMClient

__all__ = [
    "BAI_DEFAULT_BASE_URL",
    "BAI_DEFAULT_MODEL",
    "AnthropicClientError",
    "AnthropicLLMClient",
    "AzureOpenAIClientError",
    "AzureOpenAILLMClient",
    "BaiClientError",
    "BaiLLMClient",
    "OpenAIClientError",
    "OpenAILLMClient",
    "StubLLMClient",
]
