"""CatalogRetrievalService: the real products for a set of search words.

Uses the Phase 4 `SearchBackend` through the same `selectors.product_queryset()` the shop's
listing uses, so the assistant can only ever show what a customer could find by searching.
Phase 13 replaces the backend (semantic/hybrid) behind the same `search()` contract; this
module does not change.
"""

import re
from decimal import Decimal

from django.conf import settings
from django.db.models import QuerySet

from apps.catalog import selectors
from apps.catalog.models import Product, ProductVariant
from apps.catalog.search import get_search_backend

from . import vocabulary as V
from .schemas import ProductMatch

PER_TERM = 3  # best products per search word before merging


def _whole_word(product: Product, term: str) -> bool:
    words = [w for w in re.findall(r"[\w.]+", term.lower()) if w]
    haystack = " ".join(
        str(part).lower()
        for part in (
            product.name,
            product.category.name if product.category_id else "",
            product.subcategory.name if product.subcategory_id else "",
            " ".join(product.tags or []),
        )
    )
    return all(re.search(rf"(?<![a-z]){re.escape(w)}(?:s|es)?(?![a-z])", haystack) for w in words)


class CatalogRetrievalService:
    def __init__(self, backend=None):
        self.backend = backend or get_search_backend()

    def base(self) -> QuerySet[Product]:
        return selectors.product_queryset()

    def search(self, term: str, *, budget: Decimal | None = None, limit: int = PER_TERM) -> list[Product]:
        """Products matching one search word (all words of the term), best first, priced ≤ budget."""
        result = self.backend.search(self.base(), term)
        if result.matched != "all_terms":
            return []
        qs = result.queryset
        if budget is not None:
            qs = qs.filter(price__lte=budget)
        rows = list(selectors.order_products(qs, "relevance", searching=True)[: limit * 3])
        # The keyword search matches inside words ("tap" is inside "tape"); for the assistant a
        # whole-word match in the name, category or tags wins whenever there is one.
        exact = [p for p in rows if _whole_word(p, term)]
        return (exact or rows)[:limit]

    def find(
        self, terms: list[str], *, budget: Decimal | None = None, language: str = "en", limit: int | None = None
    ) -> tuple[list[ProductMatch], list[str]]:
        """Products for every term, merged and de-duplicated, with the terms nothing matched."""
        limit = limit or settings.AI_ASSISTANT_MAX_PRODUCTS
        matches: list[ProductMatch] = []
        seen: set[int] = set()
        missing: list[str] = []
        for term in terms:
            found = self.search(term, budget=budget)
            if not found:
                missing.append(term)
                continue
            for product in found:
                if product.pk in seen or product.cheapest_variant_id is None:
                    continue
                seen.add(product.pk)
                matches.append(
                    ProductMatch(
                        product=product,
                        variant_id=product.cheapest_variant_id,
                        price=product.price,
                        reason=V.text(language, "reason_term", term=term),
                        term=term,
                        relevance=int(getattr(product, "relevance", 0) or 0),
                    )
                )
        return matches[:limit], missing

    def within_budget(self, budget: Decimal, *, language: str = "en", limit: int | None = None) -> list[ProductMatch]:
        """Popular products priced within the budget, for "what can I get for ₹1000"."""
        limit = limit or settings.AI_ASSISTANT_MAX_PRODUCTS
        qs = self.base().filter(price__lte=budget, price__isnull=False, stock_total__gt=0)
        rows = qs.order_by("-sold_count", "-rating_avg", "-is_featured", "price", "id")[:limit]
        return [
            ProductMatch(
                product=p,
                variant_id=p.cheapest_variant_id,
                price=p.price,
                reason=V.text(language, "reason_budget"),
                term="",
            )
            for p in rows
            if p.cheapest_variant_id is not None
        ]

    def products_by_id(self, product_ids: list[int]) -> dict[int, Product]:
        """Live rows for stored references (deleted/unpublished ones are simply absent)."""
        rows = self.base().filter(pk__in=product_ids)
        return {p.pk: p for p in rows}

    @staticmethod
    def variant_belongs(variant_id: int, product_id: int) -> bool:
        return ProductVariant.objects.filter(pk=variant_id, product_id=product_id, is_active=True).exists()
