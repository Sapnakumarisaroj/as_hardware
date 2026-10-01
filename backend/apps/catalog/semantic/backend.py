"""HybridSearchBackend: keyword + related words + meaning, ranked over real products.

For a query it collects three kinds of evidence, each for products that exist in the database:

    keyword    the ordinary keyword search on the customer's own words (Phase 4)
    related    the same search on the catalogue words the query *means* (expand.py)
    semantic   cosine similarity between the query and each product's stored vector (index.py)

Their scores are added: a product that matches the words AND the meaning ranks above one that only
matches one of them. Whenever the extra parts have nothing to add, or fail, the plain keyword
result is returned unchanged, so search never gets worse than before and never breaks.
"""

import logging
import re
from dataclasses import dataclass, field

from django.db.models import Case, IntegerField, QuerySet, Value, When

from ..models import Product, ProductVariant
from ..search import KeywordSearchBackend, SearchResult, _forms
from . import index
from .embedders import get_embedder
from .expand import Expansion, expand

logger = logging.getLogger(__name__)

RELATED_WEIGHT = 0.6  # a related word counts less than the customer's own word
NAME_POINTS = 12  # a related word found in the product name
OTHER_POINTS = 6  # … in its category, brand or tags
RELATED_CAP = 40
SEMANTIC_WEIGHT = 40  # points for a perfect semantic match
SEMANTIC_ONLY_MIN = 0.15  # a semantic-only product needs at least this share of the range
CANDIDATES = 120  # most products scored per query
SEMANTIC_POOL = 60  # nearest vectors fetched before the listing filters are applied
SHORT_TERM = 3  # query words this short must match a whole word ("ac" is not in "Hacksaw")


def _matches_word(term: str, text: str, *, prefix: bool) -> bool:
    """`term` (or its singular) as a word in `text`: at the start of a word when `prefix` ("drill" in
    "drilling"), otherwise the whole word with an optional plural ("tap" in "taps", not in "tape")."""
    end = "" if prefix else r"(?:s|es)?(?![a-z0-9])"
    return any(re.search(rf"(?<![a-z0-9]){re.escape(form)}{end}", text) for form in _forms(term))


def _query_word_matches(term: str, text: str) -> bool:
    return _matches_word(term, text, prefix=len(term) > SHORT_TERM)


@dataclass
class Scored:
    query: str
    base: SearchResult
    expansion: Expansion
    keyword: dict[int, int] = field(default_factory=dict)
    related: dict[int, int] = field(default_factory=dict)
    semantic: dict[int, float] = field(default_factory=dict)  # normalised 0..1
    cosine: dict[int, float] = field(default_factory=dict)
    haystack: dict[int, str] = field(default_factory=dict)  # product id -> name, categories, brand, tags
    fulltext: dict[int, str] = field(default_factory=dict)  # … plus SKUs, variant names and descriptions
    names: dict[int, str] = field(default_factory=dict)
    embedder: str = "none"

    def final(self, pid: int) -> int:
        return round(
            self.keyword.get(pid, 0)
            + RELATED_WEIGHT * self.related.get(pid, 0)
            + SEMANTIC_WEIGHT * self.semantic.get(pid, 0)
        )

    def ids(self) -> list[int]:
        pool = set(self.keyword) | set(self.related) | set(self.semantic)
        return sorted(pool, key=lambda pid: (-self.final(pid), pid))[:CANDIDATES]


class HybridSearchBackend:
    name = "hybrid"

    def __init__(self):
        self.keyword = KeywordSearchBackend()

    # --- Public contract (same as KeywordSearchBackend) -------------------------------------------

    def search(self, qs: QuerySet[Product], query: str) -> SearchResult:
        base = self.keyword.search(qs, query)
        if not base.terms:
            return base
        try:
            scored = self.score(qs, query, base)
        except Exception:  # noqa: BLE001 — any failure in the extra parts means plain keyword search
            logger.exception("Semantic search failed; using keyword search")
            return base
        if scored is None:
            return base
        return self._result(qs, scored)

    # --- Scoring ----------------------------------------------------------------------------------

    def score(self, qs: QuerySet[Product], query: str, base: SearchResult | None = None) -> Scored | None:
        """All the evidence for `query`, or None when only the keyword result applies."""
        base = base or self.keyword.search(qs, query)
        expansion = expand(query, index.catalogue_words())
        words = set(query.lower().split())
        expansion.terms = [t for t in expansion.terms if t not in words and t != query.lower()]
        scored = Scored(query=query, base=base, expansion=expansion, embedder=get_embedder().kind)

        scored.keyword = dict(base.queryset.order_by("-relevance", "pk").values_list("pk", "relevance")[:CANDIDATES])
        related_ids: list[int] = []
        if expansion.terms:
            found = self.keyword.any_terms(qs, expansion.terms).order_by("-relevance", "pk")
            related_ids = list(found.values_list("pk", flat=True)[:CANDIDATES])

        nearest = index.similarities(" ".join([query, *expansion.terms]), top=SEMANTIC_POOL)
        visible = set(qs.filter(pk__in=list(nearest)).values_list("pk", flat=True)) if nearest else set()
        floor = get_embedder().min_score
        best, margin = max(nearest.values(), default=0.0), get_embedder().margin
        for pid, cosine in nearest.items():
            if pid not in visible or cosine < best - margin:
                continue  # far behind the best match: probably not what was meant
            share = (cosine - floor) / (1 - floor)
            if pid in scored.keyword or pid in related_ids or share >= SEMANTIC_ONLY_MIN:
                scored.semantic[pid] = share
                scored.cosine[pid] = cosine
        partial = base.matched == "some_terms"
        if not related_ids and not scored.semantic and not partial:
            return None

        pool = set(scored.keyword) | set(related_ids) | set(scored.semantic)
        rows = qs.filter(pk__in=pool).values_list(
            "pk", "name", "category__name", "subcategory__name", "brand__name", "tags", "sku",
            "short_description", "description",
        )  # fmt: skip
        variants: dict[int, list[str]] = {}
        for pid, vname, vsku in ProductVariant.objects.filter(product_id__in=pool, is_active=True).values_list(
            "product_id", "name", "sku"
        ):
            variants.setdefault(pid, []).extend((vname, vsku))
        for pid, name, category, sub, brand, tags, sku, short, description in rows:
            scored.names[pid] = (name or "").lower()
            scored.haystack[pid] = " ".join(str(x) for x in (name, category, sub, brand, *(tags or [])) if x).lower()
            extra = " ".join(x for x in (sku, short, description, *variants.get(pid, [])) if x).lower()
            scored.fulltext[pid] = f"{scored.haystack[pid]} {extra}"
        dropped = False
        if partial:
            # Only some words matched, by substring: "ac" is inside "Hacksaw", "me" inside "Helmet". Keep the
            # products where at least one query word really is a word; the rest are accidents of spelling.
            for pid in list(scored.keyword):
                if not any(_query_word_matches(t, scored.fulltext.get(pid, "")) for t in base.terms):
                    del scored.keyword[pid]
                    dropped = True
        for pid in related_ids:
            if pid in scored.haystack and (points := self._related_points(expansion, scored, pid)):
                scored.related[pid] = points
        if not scored.related and not scored.semantic and not dropped:
            return None  # nothing to add or remove: the keyword result stands as it is
        return scored

    @staticmethod
    def _related_points(expansion: Expansion, scored: Scored, pid: int) -> int:
        """Points for the product words the query points to: in the name more than elsewhere, and more
        when several parts of the query point to the same word. 0 when the word only occurs inside
        another word ("tap" in "tape")."""
        name, haystack, fulltext = scored.names[pid], scored.haystack[pid], scored.fulltext[pid]
        points, anywhere = 0.0, False
        for term in expansion.terms:
            if _matches_word(term, name, prefix=False):
                weight = NAME_POINTS
            elif _matches_word(term, haystack, prefix=False):
                weight = OTHER_POINTS
            else:
                anywhere = anywhere or _matches_word(term, fulltext, prefix=False)
                continue
            points += weight * min(1 + 0.5 * (expansion.counts.get(term, 1) - 1), 2.0)
        if points:
            return round(min(points, RELATED_CAP))
        return 1 if anywhere else 0  # 1: the word is only in the description

    def _result(self, qs: QuerySet[Product], scored: Scored) -> SearchResult:
        ids = [pid for pid in scored.ids() if pid in scored.haystack]
        if not ids:
            return SearchResult(
                qs.none().annotate(relevance=Value(0, output_field=IntegerField())),
                scored.base.terms,
                "none",
                mode="hybrid",
                related_terms=tuple(scored.expansion.terms),
            )
        relevance = Case(
            *[When(pk=pid, then=Value(max(scored.final(pid), 1))) for pid in ids],
            default=Value(0),
            output_field=IntegerField(),
        )
        queryset = qs.filter(pk__in=ids).annotate(relevance=relevance)
        if scored.keyword and scored.base.matched == "all_terms":
            matched = "all_terms"
        elif scored.keyword:
            matched = "some_terms"
        else:
            matched = "related"
        return SearchResult(
            queryset,
            scored.base.terms,
            matched,
            mode="hybrid",
            related_terms=tuple(scored.expansion.terms),
            reasons={pid: self.reason(scored, pid) for pid in ids},
        )

    # --- Explanations -----------------------------------------------------------------------------

    @staticmethod
    def reason(scored: Scored, pid: int) -> dict:
        """Why this product is here, in words a customer understands (no scores)."""
        if scored.keyword.get(pid):
            partial = scored.base.matched != "all_terms"
            return {"type": "keyword", "text": "Matches some of your words" if partial else "Matches your search"}
        if scored.related.get(pid):
            fulltext = scored.fulltext.get(pid, "")
            typos = {right: wrong for wrong, right in scored.expansion.typos.items()}
            for term in scored.expansion.terms:
                if not _matches_word(term, fulltext, prefix=False):
                    continue
                if term in typos:
                    return {"type": "related", "text": f"Showing “{term}” for “{typos[term]}”"}
                source = scored.expansion.sources.get(term, "")
                if source and source != term:
                    return {"type": "related", "text": f"For “{source}”: {term}"}
                return {"type": "related", "text": f"Related to your search: {term}"}
            return {"type": "related", "text": "Related to your search"}
        return {"type": "semantic", "text": "Similar to what you described"}

    def analyse(self, qs: QuerySet[Product], query: str) -> dict:
        """For the admin/developer diagnostics: every component of every score."""
        base = self.keyword.search(qs, query)
        scored = self.score(qs, query, base)
        names = dict(
            qs.filter(
                pk__in=scored.ids() if scored else list(base.queryset.values_list("pk", flat=True)[:CANDIDATES])
            ).values_list("pk", "name")
        )
        if scored is None:
            rows = [
                {
                    "product_id": pid,
                    "name": names.get(pid, ""),
                    "keyword": score,
                    "related": 0,
                    "semantic": 0.0,
                    "cosine": None,
                    "final": score,
                }
                for pid, score in dict(
                    base.queryset.order_by("-relevance", "pk").values_list("pk", "relevance")[:CANDIDATES]
                ).items()
            ]
            return {
                "mode": "keyword",
                "terms": list(base.terms),
                "related_terms": [],
                "matched": base.matched,
                "results": rows,
            }
        rows = [
            {
                "product_id": pid,
                "name": names.get(pid, ""),
                "keyword": scored.keyword.get(pid, 0),
                "related": scored.related.get(pid, 0),
                "semantic": round(scored.semantic.get(pid, 0.0), 3),
                "cosine": round(scored.cosine[pid], 3) if pid in scored.cosine else None,
                "final": scored.final(pid),
                "reason": self.reason(scored, pid),
            }
            for pid in scored.ids()
            if pid in names
        ]
        return {
            "mode": "hybrid",
            "embedder": scored.embedder,
            "terms": list(base.terms),
            "related_terms": scored.expansion.terms,
            "sources": scored.expansion.sources,
            "matched": base.matched,
            "results": rows,
        }
