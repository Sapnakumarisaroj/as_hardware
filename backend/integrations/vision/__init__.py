from functools import lru_cache

from django.conf import settings

from .base import Guess, Kind, VisionError, VisionProvider, VisionResult, VisionUnavailable
from .providers import (
    AnthropicVisionProvider,
    ClipVisionProvider,
    NoVisionProvider,
    OllamaVisionProvider,
    OpenAICompatibleVisionProvider,
)

PROVIDERS = {
    "none": NoVisionProvider,
    "clip": ClipVisionProvider,
    "ollama": OllamaVisionProvider,
    "openai_compatible": OpenAICompatibleVisionProvider,
    "anthropic": AnthropicVisionProvider,
}


@lru_cache(maxsize=4)
def _make(name: str, model: str) -> VisionProvider:
    cls = PROVIDERS.get(name, NoVisionProvider)
    return cls() if cls is NoVisionProvider else cls(model)


def get_vision_provider() -> VisionProvider:
    """The provider named by VISION_PROVIDER (unknown names mean "none", so a typo can't break the site)."""
    return _make(settings.VISION_PROVIDER, settings.VISION_MODEL)


def reset_vision_provider() -> None:
    _make.cache_clear()


def warm_up_in_background(kinds_factory=None) -> None:
    """Load a local model at server start so the first photo doesn't wait for it."""
    provider = get_vision_provider()
    if isinstance(provider, ClipVisionProvider) and not provider.loaded:
        provider.warm_up(kinds_factory)


__all__ = [
    "Guess",
    "Kind",
    "VisionError",
    "VisionProvider",
    "VisionResult",
    "VisionUnavailable",
    "get_vision_provider",
    "reset_vision_provider",
    "warm_up_in_background",
]
