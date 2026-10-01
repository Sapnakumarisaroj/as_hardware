"""Text → vector. An embedder turns a sentence into a list of numbers so that texts with a
similar meaning (or, for the hashing embedder, similar spelling) are close together.

    none                   semantic search off (keyword + related words only)
    hashing                no dependencies, no download: character n-grams hashed into a fixed
                           vector. Tolerates typos and word forms; does not know synonyms.
    sentence_transformers  a local open-source model (e.g. paraphrase-multilingual-MiniLM). Knows
                           meaning across English and Hindi. Needs `pip install sentence-transformers`
                           (requirements/semantic.txt) and a one-time model download; not for shared hosting.

Every embedder returns L2-normalised vectors, so cosine similarity is a plain dot product.
"""

import logging
import math
import re
import threading
import time
import zlib
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[\w]+", re.UNICODE)


class Embedder:
    kind = "base"
    dimensions = 0
    min_score = 0.3  # cosine below this is treated as "not related"
    margin = 1.0  # a match must be within this cosine distance of the best one (1.0: no limit)

    @property
    def key(self) -> str:
        """Identifies the vector space: stored vectors from another key are stale."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"kind": self.kind, "key": self.key, "available": self.available, "dimensions": self.dimensions}


class NoEmbedder(Embedder):
    kind = "none"

    @property
    def key(self) -> str:
        return "none"

    @property
    def available(self) -> bool:
        return False

    def embed(self, texts):
        raise RuntimeError("Semantic embeddings are switched off (SEMANTIC_EMBEDDER=none).")


class HashingEmbedder(Embedder):
    """Character 3–5-grams of every word (plus the whole word), hashed into `dimensions` buckets."""

    kind = "hashing"
    dimensions = 512
    min_score = 0.28

    @property
    def key(self) -> str:
        return f"hashing-v1-{self.dimensions}"

    def _features(self, text: str):
        for word in _WORD.findall(text.lower()):
            yield f"w:{word}", 2.0
            padded = f" {word} "
            for n in (3, 4, 5):
                for i in range(len(padded) - n + 1):
                    yield f"c:{padded[i : i + n]}", 1.0

    def embed(self, texts):
        vectors = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for feature, weight in self._features(text):
                h = zlib.crc32(feature.encode("utf-8"))
                vec[h % self.dimensions] += weight if (h >> 16) & 1 else -weight
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class SentenceTransformerEmbedder(Embedder):
    kind = "sentence_transformers"
    min_score = 0.30
    margin = 0.08
    RETRY_AFTER = 60  # seconds before a failed model load is tried again

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._failed_at = 0.0
        self._lock = threading.Lock()
        self.dimensions = 0

    @property
    def key(self) -> str:
        return f"st:{self.model_name}"

    def _load(self):
        if self._model is not None:
            return self._model
        if self._failed_at and time.monotonic() - self._failed_at < self.RETRY_AFTER:
            return None
        if not self._lock.acquire(blocking=False):
            return None  # another thread is loading it: this search uses keywords meanwhile
        try:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer

                kwargs = {"local_files_only": True} if settings.SEMANTIC_MODEL_LOCAL_ONLY else {}
                self._model = SentenceTransformer(self.model_name, **kwargs)
                getter = (
                    getattr(self._model, "get_embedding_dimension", None)
                    or self._model.get_sentence_embedding_dimension
                )
                self.dimensions = int(getter())
                self._failed_at = 0.0
            except Exception as exc:  # noqa: BLE001 — missing package, no download, corrupt cache …
                logger.warning("Semantic model %s is unavailable: %s", self.model_name, exc)
                self._failed_at = time.monotonic()
                self._model = None
        finally:
            self._lock.release()
        return self._model

    @property
    def available(self) -> bool:
        return self._load() is not None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def embed(self, texts):
        model = self._load()
        if model is None:
            raise RuntimeError(f"Semantic model {self.model_name} is not available.")
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        return [[float(x) for x in row] for row in vectors]

    def describe(self):
        info = super().describe()
        info.update(model=self.model_name, loaded=self.loaded)
        return info


@lru_cache(maxsize=8)
def _make(kind: str, model: str) -> Embedder:
    if kind == "hashing":
        return HashingEmbedder()
    if kind == "sentence_transformers":
        return SentenceTransformerEmbedder(model)
    return NoEmbedder()


def get_embedder() -> Embedder:
    """The embedder named in settings. Unknown names mean "none", so a typo can't break the site."""
    return _make(settings.SEMANTIC_EMBEDDER, settings.SEMANTIC_MODEL)


def warm_up_in_background() -> None:
    """Load a local model in a background thread when the web server starts, so the first customer
    search doesn't wait for it (loading takes 10–20 s on a laptop CPU). Searches made before it is ready
    still work: the model loads under a lock, and anything that fails falls back to keyword search."""
    embedder = get_embedder()
    if isinstance(embedder, SentenceTransformerEmbedder) and not embedder.loaded:
        threading.Thread(target=embedder._load, name="semantic-warm-up", daemon=True).start()
