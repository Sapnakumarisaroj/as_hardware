"""The search index: one `ProductEmbedding` per product, kept in step with the product's words."""

import hashlib
import logging
import re
from array import array
from dataclasses import dataclass, field

from django.db.models import Count, Max

from ..models import Product, ProductEmbedding
from .embedders import get_embedder

logger = logging.getLogger(__name__)

try:  # numpy only comes with sentence-transformers; without it the same maths runs in plain Python
    import numpy as np
except ImportError:  # pragma: no cover - exercised when numpy is absent
    np = None

BATCH = 32
MAX_DESCRIPTION = 160
_QUERY_CACHE: dict[tuple[str, str], list[float]] = {}
_QUERY_CACHE_SIZE = 256
_MATRIX: dict = {"stamp": None, "ids": [], "matrix": None}


def product_text(product: Product) -> str:
    """What a product *is*, as one short text: name, categories and tags first, then the short
    description. Real catalogue fields only. Long descriptions, brand names and specification tables are
    left out on purpose: they dilute the meaning of the name (keyword search still covers them)."""
    parts = [product.name, product.category.name]
    if product.subcategory_id:
        parts.append(product.subcategory.name)
    parts.extend(t for t in (product.tags or []) if isinstance(t, str))
    if product.short_description:
        parts.append(product.short_description[:MAX_DESCRIPTION])
    return ". ".join(p.strip() for p in parts if p and p.strip())


def _fingerprint(text: str, embedder_key: str) -> str:
    return hashlib.sha256(f"{embedder_key}\n{text}".encode()).hexdigest()


def _pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def _unpack(blob) -> array:
    values = array("f")
    values.frombytes(bytes(blob))
    return values


def _products():
    return Product.objects.select_related("brand", "category", "subcategory").prefetch_related(
        "variants", "specifications"
    )


@dataclass
class SyncResult:
    embedded: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"embedded": self.embedded, "unchanged": self.unchanged, "removed": self.removed, "failed": self.failed}


def sync_products(products=None, *, force: bool = False) -> SyncResult:
    """Embed the products whose text (or embedder) changed. `force` embeds every one again.

    Raises RuntimeError when the embedder is not available; the caller decides what to do.
    """
    embedder = get_embedder()
    if not embedder.available:
        raise RuntimeError(f"Embedder '{embedder.kind}' is not available.")
    result = SyncResult()
    whole_catalogue = products is None
    rows = list(_products() if whole_catalogue else products)
    existing = {e.product_id: e for e in ProductEmbedding.objects.filter(product_id__in=[p.pk for p in rows])}
    pending: list[tuple[Product, str, str]] = []
    for product in rows:
        text = product_text(product)
        digest = _fingerprint(text, embedder.key)
        current = existing.get(product.pk)
        if not force and current and current.text_hash == digest and current.embedder == embedder.key:
            result.unchanged += 1
        else:
            pending.append((product, text, digest))
    for start in range(0, len(pending), BATCH):
        chunk = pending[start : start + BATCH]
        try:
            vectors = embedder.embed([text for _, text, _ in chunk])
        except Exception as exc:  # noqa: BLE001 — one bad batch must not stop the rest
            logger.warning("Embedding batch failed: %s", exc)
            result.failed.extend(p.name for p, _, _ in chunk)
            continue
        for (product, _text, digest), vector in zip(chunk, vectors, strict=True):
            ProductEmbedding.objects.update_or_create(
                product=product,
                defaults={
                    "embedder": embedder.key,
                    "dimensions": len(vector),
                    "vector": _pack(vector),
                    "text_hash": digest,
                },
            )
            result.embedded += 1
    if whole_catalogue:
        result.removed = ProductEmbedding.objects.exclude(product__in=Product.objects.all()).delete()[0]
    return result


def sync_product(product_id: int) -> bool:
    """Refresh one product (removes the row if the product is gone or soft-deleted)."""
    product = _products().filter(pk=product_id).first()
    if product is None:
        ProductEmbedding.objects.filter(product_id=product_id).delete()
        return False
    sync_products([product])
    return True


def status() -> dict:
    """What the admin tools show: is the index there, complete and current?"""
    embedder = get_embedder()
    total = Product.objects.count()
    current = ProductEmbedding.objects.filter(embedder=embedder.key)
    indexed = current.count()
    missing = stale = 0
    if embedder.available:
        hashes = dict(current.values_list("product_id", "text_hash"))
        for product in _products():
            stored = hashes.get(product.pk)
            if stored is None:
                missing += 1
            elif stored != _fingerprint(product_text(product), embedder.key):
                stale += 1
    return {
        "embedder": embedder.describe(),
        "products": total,
        "indexed": indexed,
        "missing": missing,
        "stale": stale,
        "other_embedder": ProductEmbedding.objects.exclude(embedder=embedder.key).count(),
        "last_updated": current.aggregate(m=Max("updated_at"))["m"],
        "ready": embedder.available and indexed > 0,
    }


def _matrix():
    """(ids, matrix) of the current embedder's vectors, cached until a row changes."""
    embedder = get_embedder()
    agg = ProductEmbedding.objects.filter(embedder=embedder.key).aggregate(n=Count("pk"), m=Max("updated_at"))
    stamp = (embedder.key, agg["n"], agg["m"])
    if _MATRIX["stamp"] == stamp:
        return _MATRIX["ids"], _MATRIX["matrix"]
    ids, vectors = [], []
    for pid, blob in ProductEmbedding.objects.filter(embedder=embedder.key).values_list("product_id", "vector"):
        ids.append(pid)
        vectors.append(_unpack(blob))
    matrix = np.array(vectors, dtype="float32") if np is not None and vectors else vectors
    _MATRIX.update(stamp=stamp, ids=ids, matrix=matrix)
    return ids, matrix


def _query_vector(text: str) -> list[float]:
    embedder = get_embedder()
    key = (embedder.key, text)
    if key not in _QUERY_CACHE:
        if len(_QUERY_CACHE) >= _QUERY_CACHE_SIZE:
            _QUERY_CACHE.pop(next(iter(_QUERY_CACHE)))
        _QUERY_CACHE[key] = embedder.embed([text])[0]
    return _QUERY_CACHE[key]


def similarities(text: str, allowed_ids: set[int] | None = None, *, top: int = 30) -> dict[int, float]:
    """Cosine similarity of `text` to indexed products (best `top`, above the embedder's cut-off).

    Empty when the embedder is off/unavailable or nothing is indexed: the caller falls back to keywords.
    """
    embedder = get_embedder()
    if not text.strip() or not embedder.available:
        return {}
    ids, matrix = _matrix()
    if not ids:
        return {}
    query = _query_vector(text)
    if np is not None:
        scores = (matrix @ np.array(query, dtype="float32")).tolist()
    else:
        scores = [sum(a * b for a, b in zip(row, query, strict=True)) for row in matrix]
    ranked = sorted(zip(ids, scores, strict=True), key=lambda pair: -pair[1])
    out: dict[int, float] = {}
    for pid, score in ranked:
        if score < embedder.min_score or len(out) >= top:
            break
        if allowed_ids is None or pid in allowed_ids:
            out[pid] = float(score)
    return out


_WORDS: dict = {"stamp": None, "words": frozenset()}


def catalogue_words() -> frozenset[str]:
    """Every word the catalogue uses in names, tags, categories and brands (for typo correction)."""
    agg = Product.objects.aggregate(n=Count("pk"), m=Max("updated_at"))
    stamp = (agg["n"], agg["m"])
    if _WORDS["stamp"] != stamp:
        words: set[str] = set()
        for row in Product.objects.values_list("name", "tags", "category__name", "subcategory__name", "brand__name"):
            text = " ".join(str(x) for x in (row[0], *(row[1] or []), row[2], row[3], row[4]) if x)
            words.update(w for w in re.findall(r"[a-z]{4,}", text.lower()))
        _WORDS.update(stamp=stamp, words=frozenset(words))
    return _WORDS["words"]


def reset_caches() -> None:
    _WORDS.update(stamp=None, words=frozenset())
    _QUERY_CACHE.clear()
    _MATRIX.update(stamp=None, ids=[], matrix=None)
