from functools import lru_cache

from django.conf import settings

from .base import ChatOptions, LLMError, LLMProvider, LLMReply, LLMUnavailable
from .providers import AnthropicProvider, NoLLMProvider, OllamaProvider, OpenAICompatibleProvider

PROVIDERS = {
    "none": NoLLMProvider,
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
}


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """The provider named by LLM_PROVIDER (unknown names mean "none", so a typo can't break the site)."""
    return PROVIDERS.get(settings.LLM_PROVIDER, NoLLMProvider)()


def reset_llm_provider() -> None:
    get_llm_provider.cache_clear()


__all__ = [
    "ChatOptions",
    "LLMError",
    "LLMProvider",
    "LLMReply",
    "LLMUnavailable",
    "get_llm_provider",
    "reset_llm_provider",
]
