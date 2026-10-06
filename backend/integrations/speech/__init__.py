from functools import lru_cache

from django.conf import settings

from .base import (
    AudioTooLong,
    SpeechAudio,
    SpeechError,
    SpeechUnavailable,
    STTProvider,
    Transcript,
    TTSProvider,
)
from .providers import (
    FasterWhisperSTTProvider,
    NoSTTProvider,
    NoTTSProvider,
    OpenAICompatibleSTTProvider,
    OpenAICompatibleTTSProvider,
)

STT_PROVIDERS = {
    "none": NoSTTProvider,
    "faster_whisper": FasterWhisperSTTProvider,
    "openai_compatible": OpenAICompatibleSTTProvider,
}
TTS_PROVIDERS = {
    "none": NoTTSProvider,
    "openai_compatible": OpenAICompatibleTTSProvider,
}


@lru_cache(maxsize=4)
def _make_stt(name: str, model: str) -> STTProvider:
    cls = STT_PROVIDERS.get(name, NoSTTProvider)
    return cls() if cls is NoSTTProvider else cls(model)


@lru_cache(maxsize=4)
def _make_tts(name: str, model: str) -> TTSProvider:
    cls = TTS_PROVIDERS.get(name, NoTTSProvider)
    return cls() if cls is NoTTSProvider else cls(model)


def get_stt_provider() -> STTProvider:
    """The provider named by SPEECH_STT_PROVIDER (unknown names mean "none", so a typo can't break the site)."""
    return _make_stt(settings.SPEECH_STT_PROVIDER, settings.SPEECH_STT_MODEL)


def get_tts_provider() -> TTSProvider:
    return _make_tts(settings.SPEECH_TTS_PROVIDER, settings.SPEECH_TTS_MODEL)


def reset_speech_providers() -> None:
    _make_stt.cache_clear()
    _make_tts.cache_clear()


__all__ = [
    "AudioTooLong",
    "STTProvider",
    "SpeechAudio",
    "SpeechError",
    "SpeechUnavailable",
    "TTSProvider",
    "Transcript",
    "get_stt_provider",
    "get_tts_provider",
    "reset_speech_providers",
]
