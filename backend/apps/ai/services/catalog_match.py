"""Words → real catalogue products and the right variant, shared by voice shopping (Phase 18) and the
project builder (Phase 19).

The same path as the shop's listing: the Phase 16 search understanding (`interpret`: "53 grade", "25 kg",
"1.5 sq mm" become option/spec/category filters, applied only when they still leave results) and the
configured search backend (Phase 13 hybrid) over `selectors.product_queryset()` (published, active,
not deleted). Nothing is invented: no match means no product.
"""

from dataclasses import dataclass, field

from apps.catalog import selectors
from apps.catalog.interpret import interpret


@dataclass
class Match:
    products: list = field(default_factory=list)  # best first
    labels: list[dict] = field(default_factory=list)  # filters understood from the words
    params: dict = field(default_factory=dict)  # listing parameters used (q, opt_*, spec_*, category)
    quality: str = ""  # exact (every word matched) | closest | "" (nothing)


def find_products(query: str, *, limit: int = 3) -> Match:
    if not query:
        return Match()
    base = selectors.product_queryset()
    params = {"q": query}
    labels = []
    found = interpret(query, params)
    if found:
        merged = {**params, **found.filters}
        if selectors.filter_products(base, merged).exists():
            params, labels = merged, found.labels
    result = selectors.apply_search(selectors.filter_products(base, params, search=False), params)
    if labels and result.matched != "all_terms":
        # A generic word read as a filter ("tape" → Sealants) can hide the product every word names
        # ("masking tape"): the plain search wins when it matches all the words and the filtered one doesn't.
        plain = {"q": query}
        unfiltered = selectors.apply_search(selectors.filter_products(base, plain, search=False), plain)
        if unfiltered.matched == "all_terms":
            params, labels, result = plain, [], unfiltered
    if result.matched == "none":
        return Match(labels=labels, params=params)
    rows = [
        p
        for p in selectors.order_products(result.queryset, None, searching=bool(result.terms))[: limit * 2]
        if p.cheapest_variant_id is not None
    ][:limit]
    return Match(rows, labels, params, "exact" if result.matched == "all_terms" else "closest")


def variant_options(variant) -> dict[str, str]:
    return {o.option_type.slug: o.value.slug for o in variant.option_values.all()}


def choose_variant(product, params: dict):
    """The active variant the words name (`opt_<type>` filters, e.g. "25 kg"), else the default one."""
    wanted = {k[len("opt_") :]: v for k, v in params.items() if k.startswith("opt_")}
    variants = [v for v in product.variants.all() if v.is_active]
    if not variants:
        return None
    fitting = [v for v in variants if all(variant_options(v).get(t) == value for t, value in wanted.items())]
    fitting = fitting or variants
    return next((v for v in fitting if v.is_default), min(fitting, key=lambda v: (v.price, v.pk)))
