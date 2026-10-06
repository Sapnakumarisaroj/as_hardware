"""Speech to text and text to speech behind two small interfaces (Phase 18).

The shop's default needs neither: the customer's browser listens (Web Speech API) and speaks
(`speechSynthesis`), so nothing is installed or paid for. A server provider is only used when the
browser can't (Firefox has no speech recognition, some phones have no Hindi voice) and the owner has
switched one on:

- speech to text: `faster_whisper` (open-source Whisper run locally, needs a VPS-class machine) or
  `openai_compatible` (any `/audio/transcriptions` endpoint: a self-hosted Whisper server or a paid API);
- text to speech: `openai_compatible` (`/audio/speech`).

A provider only turns sound into words or words into sound. What the words mean, which products they
name and what they cost is decided by the shop's own code (`apps.ai.services.voice`).
"""

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass


class SpeechError(Exception):
    """The provider answered with something unusable (or the audio could not be decoded)."""


class SpeechUnavailable(SpeechError):
    """The provider can't be used right now (not configured, model missing, server down). The caller falls back."""


class AudioTooLong(SpeechError):
    """The recording is longer than VOICE_MAX_AUDIO_SECONDS."""


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str = ""  # what the provider heard ("en", "hi"), when it says
    confidence: float | None = None  # 0..1 when the provider gives one
    duration: float | None = None  # seconds of audio
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class SpeechAudio:
    data: bytes
    content_type: str = "audio/mpeg"


class STTProvider:
    name = "none"
    model = ""

    @property
    def available(self) -> bool:
        return False

    def transcribe(self, audio: bytes, *, language: str = "", content_type: str = "") -> Transcript:
        raise SpeechUnavailable("No server speech recognition is configured.")

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model, "enabled": self.name != "none", "available": self.available}


class TTSProvider:
    name = "none"
    model = ""

    @property
    def available(self) -> bool:
        return False

    def synthesize(self, text: str, *, language: str = "") -> SpeechAudio:
        raise SpeechUnavailable("No server voice is configured.")

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model, "enabled": self.name != "none", "available": self.available}


# --- HTTP (standard library only, as for maps, payments and the language models) --------------------


def _check_url(url: str) -> None:
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.")):
        raise SpeechUnavailable("Speech services must use https (or a local server).")


def _open(req, timeout: float) -> tuple[bytes, str]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - scheme checked by _check_url
            return res.read(), res.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        if exc.code in (401, 403):
            raise SpeechUnavailable(f"The speech service refused the credentials ({exc.code}).") from exc
        if exc.code == 404:
            raise SpeechUnavailable(f"The speech service or model was not found: {detail}") from exc
        raise SpeechError(f"Speech service error {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise SpeechUnavailable(str(exc)) from exc


def post_multipart(
    url: str, fields: dict[str, str], file: tuple[str, bytes, str], *, headers: dict | None = None, timeout: float
) -> dict:
    """POST a multipart form with one file; return the JSON answer."""
    _check_url(url)
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        if value:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    filename, data, content_type = file
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n"
        ).encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST")  # noqa: S310 - checked above
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    body, _ = _open(req, timeout)
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise SpeechError("The speech service answered with something that isn't JSON.") from exc
    if not isinstance(data, dict):
        raise SpeechError("The speech service did not answer with a JSON object.")
    return data


def post_for_audio(url: str, body: dict, *, headers: dict | None = None, timeout: float) -> SpeechAudio:
    """POST JSON, return the audio bytes of the answer."""
    _check_url(url)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")  # noqa: S310 - checked above
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    data, content_type = _open(req, timeout)
    content_type = content_type.split(";")[0].strip().lower()
    if not data or not content_type.startswith("audio/"):
        raise SpeechError("The speech service did not answer with audio.")
    return SpeechAudio(data=data, content_type=content_type)
