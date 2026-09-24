"""Read queries for the catalog. Price, discount, stock, delivery and sales figures are
annotated with portable subqueries (no vendor-specific SQL), so a listing page is one query.

Listing parameters (all optional, combinable) are documented in docs/API.md → Catalog.
"""

from decimal import Decimal, InvalidOperation

from django.db.models import (
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Cast, Coalesce

from apps.inventory.models import Inventory
from apps.stores.models import Store

from .models import Category, Product, ProductSpecification, ProductVariant
from .search import SearchResult, get_search_backend, normalize_query

LOW_STOCK_DISPLAY_THRESHOLD = 5
SPEC_PARAM_PREFIX = "spec_"
TRUE_VALUES = ("1", "true", "yes")
DISCOUNT_EPSILON = 1e-6  # float rounding guard: exactly 25.00 % must pass "discount ≥ 25"

# Order states that count as a sale for "best sellers".
_SOLD_STATUSES = (
    "confirmed",
    "processing",
    "packed",
    "assigned",
    "picked_up",
    "out_for_delivery",
    "delivered",
)


def _fulfillment_inventory():
    return Inventory.objects.filter(
        is_active=True,
        store__is_active=True,
        store__is_deleted=False,
        store__accepts_orders=True,
        store__kind__in=Store.FULFILLMENT_KINDS,
    )


def _fast_delivery_inventory():
    """Stock held at a store that has an active delivery zone with fast delivery enabled."""
    from apps.delivery.models import DeliveryZone

    fast_stores = DeliveryZone.objects.filter(is_active=True, fast_delivery_enabled=True).values("store_id")
    return _fulfillment_inventory().filter(store_id__in=fast_stores, available_quantity__gt=0)


def _product_stock(inventory_qs):
    return Coalesce(
        Subquery(
            inventory_qs.filter(variant__product=OuterRef("pk"), variant__is_active=True)
            .values("variant__product")
            .annotate(total=Sum("available_quantity"))
            .values("total")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


def annotate_listing(qs: QuerySet[Product]) -> QuerySet[Product]:
    from apps.orders.models import OrderItem

    active_variants = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)
    cheapest = active_variants.order_by("price", "id")
    sold = (
        OrderItem.objects.filter(variant__product=OuterRef("pk"), order__status__in=_SOLD_STATUSES)
        .values("variant__product")
        .annotate(total=Sum("quantity"))
        .values("total")[:1]
    )
    variant_count = active_variants.values("product").annotate(n=Count("id")).values("n")[:1]
    qs = qs.annotate(
        price=Subquery(cheapest.values("price")[:1]),
        mrp=Subquery(cheapest.values("mrp")[:1]),
        cheapest_variant_id=Subquery(cheapest.values("id")[:1]),
        variant_count=Coalesce(Subquery(variant_count, output_field=IntegerField()), Value(0)),
        stock_total=_product_stock(_fulfillment_inventory()),
        fast_stock=_product_stock(_fast_delivery_inventory()),
        sold_count=Coalesce(Subquery(sold, output_field=IntegerField()), Value(0)),
    )
    # Ranking/filtering only; the API computes the displayed discount with Decimal in Python.
    # Float on purpose: SQLite stores whole-number decimals as INTEGER, so decimal arithmetic
    # there does integer division (28.86 % and 28.33 % would both rank as 28).
    return qs.annotate(
        discount_rank=ExpressionWrapper(
            Cast(F("mrp") - F("price"), FloatField()) * Value(100.0) / Cast(F("mrp"), FloatField()),
            output_field=FloatField(),
        )
    )


def product_queryset(*, include_unpublished: bool = False) -> QuerySet[Product]:
    qs = Product.objects.select_related("brand", "category", "subcategory").prefetch_related("images")
    if not include_unpublished:
        qs = qs.filter(is_active=True, is_published=True)
    return annotate_listing(qs)


def _csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()][:20]


def spec_filters(params) -> dict[str, list[str]]:
    """`spec_<key>=v1,v2` → {key: [v1, v2]} (values OR-ed within a key, AND-ed across keys)."""
    out = {}
    for name in params:
        if name.startswith(SPEC_PARAM_PREFIX) and (values := _csv(params.get(name))):
            out[name[len(SPEC_PARAM_PREFIX) :][:80]] = values
    return out


def filter_products(
    qs: QuerySet[Product], params, *, skip: tuple[str, ...] = (), search: bool = True
) -> QuerySet[Product]:
    """Apply listing filters. `skip` names filters to leave out (used for facet counts)."""
    if "category" not in skip and (slug := params.get("category")):
        category = Category.objects.filter(slug=slug, is_active=True).first()
        if category is None:
            return qs.none()
        qs = qs.filter(Q(category=category) | Q(subcategory=category))
    if "category" not in skip and (slug := params.get("subcategory")):
        qs = qs.filter(subcategory__slug=slug)
    if "brand" not in skip and (brands := _csv(params.get("brand"))):
        qs = qs.filter(brand__slug__in=brands)
    if "price" not in skip:
        if (value := _decimal(params.get("min_price"))) is not None:
            qs = qs.filter(price__gte=value)
        if (value := _decimal(params.get("max_price"))) is not None:
            qs = qs.filter(price__lte=value)
    if "rating" not in skip and (value := _decimal(params.get("rating"))) is not None:
        qs = qs.filter(rating_avg__gte=value, rating_count__gt=0)
    if "discount" not in skip and (value := _decimal(params.get("discount"))) is not None:
        qs = qs.filter(discount_rank__gte=float(value) - DISCOUNT_EPSILON)
    if "availability" not in skip:
        if params.get("in_stock") in TRUE_VALUES or params.get("availability") == "in_stock":
            qs = qs.filter(stock_total__gt=0)
        if params.get("fast_delivery") in TRUE_VALUES:
            qs = qs.filter(fast_stock__gt=0)
    if params.get("featured") in TRUE_VALUES:
        qs = qs.filter(is_featured=True)
    if params.get("bestseller") in TRUE_VALUES:
        qs = qs.filter(sold_count__gt=0)
    if excluded := _csv(params.get("exclude")):
        qs = qs.exclude(slug__in=excluded)
    if "spec" not in skip:
        for key, values in spec_filters(params).items():
            value_q = Q()
            for value in values:
                value_q |= Q(value__iexact=value)
            qs = qs.filter(pk__in=ProductSpecification.objects.filter(value_q, key=key).values("product_id"))
    if search:
        qs = apply_search(qs, params).queryset
    return qs


def apply_search(qs: QuerySet[Product], params) -> SearchResult:
    query = normalize_query(params.get("q"))
    if not query:
        return SearchResult(qs, (), "none")
    return get_search_backend().search(qs, query)


ORDERINGS = {
    "relevance": ("-relevance", "-is_featured", "name", "id"),
    "price": ("price", "id"),
    "-price": ("-price", "id"),
    "newest": ("-created_at", "-id"),
    "rating": ("-rating_avg", "-rating_count", "id"),
    "discount": ("-discount_rank", "price", "id"),
    "popular": ("-sold_count", "-rating_count", "name", "id"),
    "name": ("name", "id"),
}
DEFAULT_ORDERING = ("-is_featured", "name", "id")


def order_products(qs: QuerySet[Product], ordering: str | None, *, searching: bool = False) -> QuerySet[Product]:
    if ordering == "relevance" and not searching:
        ordering = None
    if not ordering and searching:
        ordering = "relevance"
    return qs.order_by(*ORDERINGS.get(ordering or "", DEFAULT_ORDERING))


# --- Facets ---------------------------------------------------------------------------------

SPEC_FACET_MIN_COVERAGE = 0.4  # a spec is offered as a filter when ≥40 % of results have it
SPEC_FACET_MAX_KEYS = 6
SPEC_FACET_MAX_VALUES = 15
RATING_STEPS = (4, 3)
DISCOUNT_STEPS = (10, 25, 50)


def product_facets(base: QuerySet[Product], params) -> dict:
    """Filter options with counts for the current result set.

    Each dimension is counted with every *other* active filter applied, so choosing a brand
    does not hide the remaining brands. Specification filters only appear when enough of the
    results share that specification, which keeps them relevant to the category browsed.
    """
    results = filter_products(base, params)

    def ids_without(dimension):
        return filter_products(base, params, skip=(dimension,)).values("pk")

    category = Category.objects.filter(slug=params.get("category") or "", is_active=True).first()
    if category is not None and category.parent_id is None:
        category_rows = (
            Product.objects.filter(pk__in=ids_without("category"), category=category, subcategory__isnull=False)
            .values("subcategory__slug", "subcategory__name")
            .annotate(count=Count("id"))
            .order_by("subcategory__name")
        )
        categories = [
            {"slug": r["subcategory__slug"], "name": r["subcategory__name"], "count": r["count"]} for r in category_rows
        ]
    elif category is None:
        category_rows = (
            Product.objects.filter(pk__in=ids_without("category"))
            .values("category__slug", "category__name")
            .annotate(count=Count("id"))
            .order_by("category__name")
        )
        categories = [
            {"slug": r["category__slug"], "name": r["category__name"], "count": r["count"]} for r in category_rows
        ]
    else:
        categories = []

    brand_rows = (
        Product.objects.filter(pk__in=ids_without("brand"), brand__isnull=False)
        .values("brand__slug", "brand__name")
        .annotate(count=Count("id"))
        .order_by("brand__name")
    )
    price = filter_products(base, params, skip=("price",)).aggregate(min=Min("price"), max=Max("price"))

    rating_base = filter_products(base, params, skip=("rating",))
    discount_base = filter_products(base, params, skip=("discount",))
    availability_base = filter_products(base, params, skip=("availability",))

    total = results.count()
    return {
        "total": total,
        "categories": categories,
        "brands": [{"slug": r["brand__slug"], "name": r["brand__name"], "count": r["count"]} for r in brand_rows],
        "price": {"min": _money(price["min"]), "max": _money(price["max"])},
        "ratings": [
            {"min": step, "count": rating_base.filter(rating_avg__gte=step, rating_count__gt=0).count()}
            for step in RATING_STEPS
        ],
        "discounts": [
            {"min": step, "count": discount_base.filter(discount_rank__gte=step - DISCOUNT_EPSILON).count()}
            for step in DISCOUNT_STEPS
        ],
        "availability": {
            "in_stock": availability_base.filter(stock_total__gt=0).count(),
            "fast_delivery": availability_base.filter(fast_stock__gt=0).count(),
        },
        "specifications": _spec_facets(ids_without("spec"), total_for_coverage=total, selected=spec_filters(params)),
    }


def _spec_facets(product_ids, *, total_for_coverage: int, selected: dict[str, list[str]]) -> list[dict]:
    rows = list(
        ProductSpecification.objects.filter(product_id__in=product_ids)
        .values("key", "name", "unit", "value")
        .annotate(count=Count("product_id", distinct=True))
    )
    by_key: dict[str, dict] = {}
    for row in rows:
        entry = by_key.setdefault(
            row["key"], {"key": row["key"], "name": row["name"], "unit": row["unit"], "values": []}
        )
        entry["values"].append({"value": row["value"], "count": row["count"]})
    facets = []
    minimum = max(2, round(total_for_coverage * SPEC_FACET_MIN_COVERAGE))
    for entry in by_key.values():
        coverage = sum(v["count"] for v in entry["values"])
        distinct = len(entry["values"])
        if entry["key"] not in selected and (coverage < minimum or distinct < 2):
            continue
        entry["values"].sort(key=lambda v: (_sort_number(v["value"]), v["value"].lower()))
        entry["values"] = entry["values"][:SPEC_FACET_MAX_VALUES]
        entry["coverage"] = coverage
        facets.append(entry)
    facets.sort(key=lambda f: (f["key"] not in selected, -f["coverage"], f["name"]))
    for facet in facets:
        facet.pop("coverage")
    return facets[:SPEC_FACET_MAX_KEYS]


def _sort_number(value: str):
    try:
        return (0, Decimal(value))
    except (InvalidOperation, ValueError):
        return (1, Decimal(0))


# --- Stock ------------------------------------------------------------------------------------


def variant_stock_map(variant_ids) -> dict[int, int]:
    rows = (
        _fulfillment_inventory()
        .filter(variant_id__in=list(variant_ids))
        .values("variant_id")
        .annotate(total=Sum("available_quantity"))
    )
    return {row["variant_id"]: row["total"] or 0 for row in rows}


def variant_fast_delivery_ids(variant_ids) -> set[int]:
    return set(_fast_delivery_inventory().filter(variant_id__in=list(variant_ids)).values_list("variant_id", flat=True))


def stock_status(total: int) -> str:
    if total <= 0:
        return "out_of_stock"
    if total <= LOW_STOCK_DISPLAY_THRESHOLD:
        return "low_stock"
    return "in_stock"


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _money(value):
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))
