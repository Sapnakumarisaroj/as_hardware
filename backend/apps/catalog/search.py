"""Product search behind a small backend interface.

`get_search_backend()` returns the configured backend (settings.CATALOG_SEARCH_BACKEND).
The default `KeywordSearchBackend` is portable (SQLite / PostgreSQL / MySQL): every query
word must appear somewhere in the product (name, brand, category, tags, description,
variant name/SKU or a specification), and results are ranked by where the words matched.
If no product contains *all* the words, products matching *any* word are returned instead
and the result says so (`matched="some_terms"`).

A semantic/hybrid backend (Phase 13) implements the same `search()` contract, so the API
and the frontend do not change when it is switched on.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, QuerySet, TextField, Value, When
from django.db.models.functions import Cast
from django.utils.module_loading import import_string

from .models import Product, ProductSpecification, ProductVariant

MAX_QUERY_LENGTH = 100
MAX_TERMS = 8
STOPWORDS = {"a", "an", "and", "the", "for", "of", "with", "in", "to", "on", "by"}

# Relevance weights per place a word is found.
WEIGHTS = {
    "name": 10,
    "brand": 6,
    "category": 5,
    "tags": 4,
    "variant": 4,
    "spec": 3,
    "description": 1,
}
PHRASE_IN_NAME_BONUS = 20


@dataclass(frozen=True)
class SearchResult:
    queryset: QuerySet[Product]  # annotated with integer `relevance`
    terms: tuple[str, ...]
    matched: str  # "all_terms" | "some_terms" | "related" (synonyms / meaning, Phase 13) | "none"
    mode: str = "keyword"  # "keyword" | "hybrid"
    related_terms: tuple[str, ...] = ()  # catalogue words the query was understood as (hybrid only)
    reasons: dict = field(default_factory=dict)  # product id -> {"type": keyword|related|semantic, "text": str}


def normalize_query(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())[:MAX_QUERY_LENGTH]


def tokenize(query: str) -> tuple[str, ...]:
    """Lower-case words; keeps sizes such as "1.5" or "3/4" intact; drops stop words."""
    words = re.findall(r"[\w./\-]+", query.lower())
    terms = [w.strip(".-/") for w in words]
    terms = [t for t in terms if t and t not in STOPWORDS]
    return tuple(dict.fromkeys(terms))[:MAX_TERMS]


def _forms(term: str) -> list[str]:
    """The word plus a naive singular ("drills" → "drill", "batteries" → "battery")."""
    forms = [term]
    if len(term) > 4 and term.endswith("ies"):
        forms.append(term[:-3] + "y")
    elif len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        forms.append(term[:-1])
    return forms


def _any_form(forms: list[str], builder) -> Q:
    q = Q()
    for form in forms:
        q |= builder(form)
    return q


class KeywordSearchBackend:
    name = "keyword"

    def _term_conditions(self, term: str) -> dict[str, Q]:
        forms = _forms(term)
        variant_match = Exists(
            ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True).filter(
                _any_form(forms, lambda f: Q(name__icontains=f) | Q(sku__icontains=f))
            )
        )
        spec_match = Exists(
            ProductSpecification.objects.filter(product=OuterRef("pk")).filter(
                _any_form(forms, lambda f: Q(value__icontains=f) | Q(name__icontains=f))
            )
        )
        return {
            "name": _any_form(forms, lambda f: Q(name__icontains=f) | Q(sku__icontains=f)),
            "brand": _any_form(forms, lambda f: Q(brand__name__icontains=f)),
            "category": _any_form(forms, lambda f: Q(category__name__icontains=f) | Q(subcategory__name__icontains=f)),
            "tags": _any_form(forms, lambda f: Q(_search_tags__icontains=f)),
            "variant": Q(variant_match),
            "spec": Q(spec_match),
            "description": _any_form(forms, lambda f: Q(short_description__icontains=f) | Q(description__icontains=f)),
        }

    def any_terms(self, qs: QuerySet[Product], phrases: list[str]) -> QuerySet[Product]:
        """Products containing ANY of the phrases (each kept whole, e.g. "ptfe tape"), scored by where."""
        qs = qs.annotate(_search_tags=Cast("tags", TextField()))
        any_match = Q()
        score = Value(0, output_field=IntegerField())
        for phrase in phrases:
            for field_name, condition in self._term_conditions(phrase.lower()).items():
                any_match |= condition
                score = score + Case(
                    When(condition, then=Value(WEIGHTS[field_name])), default=Value(0), output_field=IntegerField()
                )
        return qs.annotate(relevance=score).filter(any_match)

    def search(self, qs: QuerySet[Product], query: str) -> SearchResult:
        terms = tokenize(query)
        if not terms:
            return SearchResult(qs.annotate(relevance=Value(0, output_field=IntegerField())), (), "none")
        qs = qs.annotate(_search_tags=Cast("tags", TextField()))

        per_term = [self._term_conditions(term) for term in terms]
        matches_term = []
        score = Value(0, output_field=IntegerField())
        for conditions in per_term:
            any_field = Q()
            for place, condition in conditions.items():
                any_field |= condition
                score = score + Case(
                    When(condition, then=Value(WEIGHTS[place])), default=Value(0), output_field=IntegerField()
                )
            matches_term.append(any_field)
        phrase = query.lower()
        score = score + Case(
            When(name__icontains=phrase, then=Value(PHRASE_IN_NAME_BONUS)),
            default=Value(0),
            output_field=IntegerField(),
        )
        qs = qs.annotate(relevance=score)

        all_terms = qs
        for condition in matches_term:
            all_terms = all_terms.filter(condition)
        if len(terms) == 1 or all_terms.exists():
            return SearchResult(all_terms, terms, "all_terms")

        any_term = Q()
        for condition in matches_term:
            any_term |= condition
        return SearchResult(qs.filter(any_term), terms, "some_terms")


@lru_cache(maxsize=1)
def get_search_backend():
    path = getattr(settings, "CATALOG_SEARCH_BACKEND", "apps.catalog.search.KeywordSearchBackend")
    return import_string(path)()
