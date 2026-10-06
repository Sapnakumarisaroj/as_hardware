"""Concrete speech providers.

- `NoSTTProvider` / `NoTTSProvider`: the default. The browser listens and speaks; the server does neither.
- `FasterWhisperSTTProvider`: OpenAI's open-source Whisper (MIT licence) through `faster-whisper`
  (CTranslate2, int8 on the CPU). `small` (~480 MB) understands Hindi and Indian English well enough
  for shopping phrases; `base` (~145 MB) is faster but weaker in Hindi. Needs `requirements/speech.txt`
  and a machine with ~1 GB free RAM, so a VPS, not shared hosting. Loaded on first use.
- `OpenAICompatibleSTTProvider` / `OpenAICompatibleTTSProvider`: any server with the OpenAI audio API
  (`/audio/transcriptions`, `/audio/speech`): a self-hosted Whisper/Piper server or a paid service the
  owner opts into. Keys stay on the server.
"""

import io
import logging
import math
import threading
import time

from django.conf import settings

from .base import (
    AudioTooLong,
    SpeechAudio,
    SpeechError,
    SpeechUnavailable,
    STTProvider,
    Transcript,
    TTSProvider,
    post_for_audio,
    post_multipart,
)

logger = logging.getLogger(__name__)

# Whisper language codes. Hinglish is spoken Hindi with English words: Whisper writes it in Devanagari
# with the English words as Whisper hears them, which the voice parser reads like Hindi.
WHISPER_LANGUAGE = {"en": "en", "hi": "hi", "hinglish": "hi"}

# Shown to Whisper as the "previous text": it makes the shop's words (and digits for numbers) more likely.
PROMPTS = {
    "en": "Add 10 bags of 53 grade cement, 2 coils of 1.5 sq mm wire, CPVC pipe, MCB, PTFE tape, wall plugs.",
    "hi": "10 बोरी सीमेंट, 2 कॉइल 1.5 sq mm वायर, CPVC पाइप, MCB, नल, पेचकस, कार्ट में डालो।",
}


def _speech_settings() -> tuple[str, str]:
    base_url = (settings.SPEECH_BASE_URL or settings.OPENAI_COMPATIBLE_BASE_URL).rstrip("/")
    api_key = settings.SPEECH_API_KEY or settings.OPENAI_COMPATIBLE_API_KEY
    return base_url, api_key


class NoSTTProvider(STTProvider):
    name = "none"


class NoTTSProvider(TTSProvider):
    name = "none"


class FasterWhisperSTTProvider(STTProvider):
    name = "faster_whisper"
    RETRY_AFTER = 60
    SAMPLE_RATE = 16000

    def __init__(self, model: str = ""):
        self.model = model or "small"
        self._model = None
        self._failed_at = 0.0
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()  # one recording at a time: Whisper already uses every CPU core

    def _load(self):
        if self._model is not None:
            return self._model
        if self._failed_at and time.monotonic() - self._failed_at < self.RETRY_AFTER:
            return None
        with self._load_lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(
                        self.model,
                        device="cpu",
                        compute_type="int8",
                        local_files_only=settings.SPEECH_MODEL_LOCAL_ONLY,
                    )
                    self._failed_at = 0.0
                except Exception as exc:  # noqa: BLE001 — package missing, no download, corrupt cache …
                    logger.warning("Speech model %s is unavailable: %s", self.model, exc)
                    self._failed_at = time.monotonic()
        return self._model

    @property
    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return not (self._failed_at and time.monotonic() - self._failed_at < self.RETRY_AFTER)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def decode(self, audio: bytes):
        """The recording as 16 kHz mono samples (any format ffmpeg/PyAV reads: WebM/Opus, Ogg, WAV, MP4, MP3)."""
        try:
            from faster_whisper import decode_audio
        except ImportError as exc:
            raise SpeechUnavailable("faster-whisper is not installed.") from exc
        try:
            samples = decode_audio(io.BytesIO(audio), sampling_rate=self.SAMPLE_RATE)
        except Exception as exc:  # noqa: BLE001 — PyAV raises its own error types for broken files
            raise SpeechError("The recording could not be read.") from exc
        if len(samples) == 0:
            raise SpeechError("The recording is empty.")
        return samples

    def transcribe(self, audio: bytes, *, language: str = "", content_type: str = "") -> Transcript:
        samples = self.decode(audio)
        duration = len(samples) / self.SAMPLE_RATE
        if duration > settings.VOICE_MAX_AUDIO_SECONDS:
            raise AudioTooLong(f"Recordings can be {settings.VOICE_MAX_AUDIO_SECONDS} seconds at most.")
        model = self._load()
        if model is None:
            raise SpeechUnavailable(f"The speech model {self.model} is not available.")
        whisper_language = WHISPER_LANGUAGE.get(language)
        with self._run_lock:
            segments, info = model.transcribe(
                samples,
                language=whisper_language,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=PROMPTS.get("hi" if whisper_language == "hi" else "en"),
            )
            segments = list(segments)
        spoken = [s for s in segments if s.no_speech_prob < 0.8 and s.text.strip()]
        text = " ".join(s.text.strip() for s in spoken).strip()
        confidence = None
        if spoken:
            confidence = round(sum(math.exp(s.avg_logprob) for s in spoken) / len(spoken), 3)
        return Transcript(
            text=text,
            language=getattr(info, "language", "") or "",
            confidence=confidence,
            duration=round(duration, 2),
            provider=self.name,
            model=self.model,
        )

    def describe(self) -> dict:
        return {**super().describe(), "loaded": self.loaded}


class OpenAICompatibleSTTProvider(STTProvider):
    name = "openai_compatible"

    def __init__(self, model: str = ""):
        self.base_url, self.api_key = _speech_settings()
        self.model = model or "whisper-1"

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def transcribe(self, audio: bytes, *, language: str = "", content_type: str = "") -> Transcript:
        if not self.available:
            raise SpeechUnavailable("No speech service address is configured.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        extension = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mp4": "m4a"}.get(
            content_type, "webm"
        )
        data = post_multipart(
            f"{self.base_url}/audio/transcriptions",
            {
                "model": self.model,
                "language": WHISPER_LANGUAGE.get(language, ""),
                "response_format": "json",
                "prompt": PROMPTS.get("hi" if WHISPER_LANGUAGE.get(language) == "hi" else "en", ""),
            },
            (f"recording.{extension}", audio, content_type),
            headers=headers,
            timeout=settings.SPEECH_TIMEOUT_SECONDS,
        )
        text = str(data.get("text") or "").strip()
        return Transcript(text=text, language=str(data.get("language") or ""), provider=self.name, model=self.model)


class OpenAICompatibleTTSProvider(TTSProvider):
    name = "openai_compatible"

    def __init__(self, model: str = ""):
        self.base_url, self.api_key = _speech_settings()
        self.model = model or "tts-1"

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def synthesize(self, text: str, *, language: str = "") -> SpeechAudio:
        if not self.available:
            raise SpeechUnavailable("No speech service address is configured.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        voice = settings.SPEECH_TTS_VOICE_HI if language == "hi" else settings.SPEECH_TTS_VOICE
        return post_for_audio(
            f"{self.base_url}/audio/speech",
            {"model": self.model, "input": text, "voice": voice, "response_format": "mp3"},
            headers=headers,
            timeout=settings.SPEECH_TIMEOUT_SECONDS,
        )


__all__ = [
    "FasterWhisperSTTProvider",
    "NoSTTProvider",
    "NoTTSProvider",
    "OpenAICompatibleSTTProvider",
    "OpenAICompatibleTTSProvider",
]
