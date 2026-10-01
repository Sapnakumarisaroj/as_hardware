"""Concrete vision providers.

- `NoVisionProvider`: photo search is off; the shop explains that and offers the text search.
- `ClipVisionProvider`: OpenAI's open-source CLIP model run locally through sentence-transformers
  (MIT licence, ~600 MB, CPU is fine). Zero-shot: it scores the photo against the item kinds the shop
  passes in, so every answer is one of them and the scores are probabilities. Default for development.
- `OllamaVisionProvider`: a local vision-language model through Ollama (e.g. `qwen2.5vl:3b`, `llava`,
  `moondream`); free, open source, describes things CLIP has no kind for.
- `OpenAICompatibleVisionProvider` / `AnthropicVisionProvider`: optional hosted models the owner opts
  into. Keys stay on the server.
"""

import logging
import threading
import time

from django.conf import settings

from integrations.llm import LLMError, LLMUnavailable
from integrations.llm.base import LLMReply, post_json

from .base import (
    Guess,
    Kind,
    VisionError,
    VisionProvider,
    VisionResult,
    VisionUnavailable,
    jpeg_base64,
    parse_answer,
    prompt_for,
)

logger = logging.getLogger(__name__)


class NoVisionProvider(VisionProvider):
    name = "none"


class ClipVisionProvider(VisionProvider):
    name = "clip"
    calibrated = True
    RETRY_AFTER = 60
    LOGIT_SCALE = 100.0  # CLIP's own temperature
    TOP = 5

    def __init__(self, model: str = ""):
        # ViT-L/14 (~1.7 GB, ~0.5 s per photo on a laptop CPU) recognises everyday tools far better than the
        # small ViT-B/32 (~600 MB, ~0.1 s); set VISION_MODEL=clip-ViT-B-32 on a weak machine.
        self.model = model or "clip-ViT-L-14"
        self._model = None
        self._failed_at = 0.0
        self._lock = threading.Lock()
        self._kind_cache: dict = {"key": None, "matrix": None}

    def _load(self):
        if self._model is not None:
            return self._model
        if self._failed_at and time.monotonic() - self._failed_at < self.RETRY_AFTER:
            return None
        if not self._lock.acquire(blocking=False):
            return None  # being loaded by another thread (warm-up): this request falls back
        try:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer

                    kwargs = {"local_files_only": True} if settings.VISION_MODEL_LOCAL_ONLY else {}
                    self._model = SentenceTransformer(self.model, **kwargs)
                    self._failed_at = 0.0
                except Exception as exc:  # noqa: BLE001 — package missing, no download, corrupt cache …
                    logger.warning("Vision model %s is unavailable: %s", self.model, exc)
                    self._failed_at = time.monotonic()
        finally:
            self._lock.release()
        return self._model

    @property
    def available(self) -> bool:
        return self._load() is not None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def warm_up(self, kinds_factory=None) -> None:
        """Load the model and prepare the kinds' text vectors in a background thread."""

        def run():
            model = self._load()
            if model is None or kinds_factory is None:
                return
            try:
                self._kind_matrix(model, kinds_factory())
            except Exception:  # noqa: BLE001 — e.g. database not migrated yet; the first photo does it instead
                logger.warning("Could not prepare the photo search labels at start-up", exc_info=True)
            finally:
                from django.db import connection

                connection.close()

        threading.Thread(target=run, name="vision-warm-up", daemon=True).start()

    def _kind_matrix(self, model, kinds: list[Kind]):
        """One normalised text vector per kind: the mean of its prompts ("prompt ensembling").

        Encoding a few hundred prompts takes a while on a CPU, so the matrix is kept in memory and in
        Django's cache (a database table in production), keyed by the model and the exact prompts."""
        import hashlib

        import numpy as np
        from django.core.cache import cache

        key = tuple((k.label, k.prompts) for k in kinds)
        if self._kind_cache["key"] != key:
            digest = hashlib.sha256(repr((self.model, key)).encode()).hexdigest()[:32]
            cache_key = f"vision:kinds:{digest}"
            matrix = cache.get(cache_key)
            if matrix is None:
                prompts = [p for k in kinds for p in k.prompts]
                vectors = model.encode(prompts, normalize_embeddings=True, show_progress_bar=False, batch_size=64)
                rows, start = [], 0
                for kind in kinds:
                    chunk = vectors[start : start + len(kind.prompts)]
                    start += len(kind.prompts)
                    mean = chunk.mean(axis=0)
                    rows.append(mean / (np.linalg.norm(mean) or 1.0))
                matrix = np.vstack(rows).astype("float32")
                cache.set(cache_key, matrix, 30 * 24 * 3600)
            self._kind_cache.update(key=key, matrix=matrix)
        return self._kind_cache["matrix"]

    def identify(self, image, kinds: list[Kind]) -> VisionResult:
        import numpy as np

        model = self._load()
        if model is None:
            raise VisionUnavailable(f"The vision model {self.model} is not available.")
        if not kinds:
            raise VisionError("No item kinds to compare the photo with.")
        matrix = self._kind_matrix(model, kinds)
        picture = model.encode([image], normalize_embeddings=True, show_progress_bar=False)[0]
        logits = self.LOGIT_SCALE * (matrix @ picture)
        logits -= logits.max()
        probabilities = np.exp(logits) / np.exp(logits).sum()
        order = np.argsort(-probabilities)[: self.TOP]
        guesses = [Guess(kinds[i].label, round(float(probabilities[i]), 4), search=kinds[i].query) for i in order]
        return VisionResult(
            guesses=guesses,
            calibrated=True,
            provider=self.name,
            model=self.model,
            extra={"cosine": round(float((matrix @ picture)[order[0]]), 4)},
        )

    def describe(self) -> dict:
        return {**super().describe(), "loaded": self.loaded}


class _ChatVisionProvider(VisionProvider):
    """Vision-language models: ask for JSON, parse it, never trust it for more than a name."""

    def _ask(self, image, prompt: str) -> LLMReply:
        raise NotImplementedError

    def identify(self, image, kinds: list[Kind]) -> VisionResult:
        if not self.available:
            raise VisionUnavailable(f"{self.name} vision is not configured.")
        try:
            reply = self._ask(image, prompt_for(kinds))
            return parse_answer(reply.json(), provider=self.name, model=self.model)
        except LLMUnavailable as exc:
            raise VisionUnavailable(str(exc)) from exc
        except LLMError as exc:
            raise VisionError(str(exc)) from exc


class OllamaVisionProvider(_ChatVisionProvider):
    name = "ollama"

    def __init__(self, model: str = ""):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = model or "qwen2.5vl:3b"

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def _ask(self, image, prompt: str) -> LLMReply:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt, "images": [jpeg_base64(image)]}],
            "stream": False,
            "format": "json",
            "think": False,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0.1, "num_predict": 300},
        }
        data = post_json(f"{self.base_url}/api/chat", body, timeout=settings.VISION_TIMEOUT_SECONDS)
        if "error" in data:
            message = str(data["error"])
            if "not found" in message.lower():
                raise LLMUnavailable(f"Ollama: {message}. Run `ollama pull {self.model}`.")
            raise LLMError(f"Ollama: {message}")
        return LLMReply(content=(data.get("message") or {}).get("content") or "", provider=self.name, model=self.model)


class OpenAICompatibleVisionProvider(_ChatVisionProvider):
    name = "openai_compatible"

    def __init__(self, model: str = ""):
        self.base_url = settings.OPENAI_COMPATIBLE_BASE_URL.rstrip("/")
        self.api_key = settings.OPENAI_COMPATIBLE_API_KEY
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def _ask(self, image, prompt: str) -> LLMReply:
        body = {
            "model": self.model,
            "max_tokens": 300,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_base64(image)}"}},
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(
            f"{self.base_url}/chat/completions", body, headers=headers, timeout=settings.VISION_TIMEOUT_SECONDS
        )
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("No answer from the vision model.")
        return LLMReply(
            content=(choices[0].get("message") or {}).get("content") or "", provider=self.name, model=self.model
        )


class AnthropicVisionProvider(_ChatVisionProvider):
    name = "anthropic"

    def __init__(self, model: str = ""):
        self.api_key = settings.ANTHROPIC_API_KEY
        self.model = model or "claude-haiku-4-5-20251001"

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _ask(self, image, prompt: str) -> LLMReply:
        body = {
            "model": self.model,
            "max_tokens": 300,
            "temperature": 0.1,
            "system": "Answer with a single JSON object and nothing else.",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_base64(image)},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = post_json(
            "https://api.anthropic.com/v1/messages", body, headers=headers, timeout=settings.VISION_TIMEOUT_SECONDS
        )
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        return LLMReply(content=text, provider=self.name, model=self.model)


__all__ = [
    "AnthropicVisionProvider",
    "ClipVisionProvider",
    "NoVisionProvider",
    "OllamaVisionProvider",
    "OpenAICompatibleVisionProvider",
    "VisionResult",
]
