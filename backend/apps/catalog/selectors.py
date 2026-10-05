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

from .models import Category, Product, ProductSpecification, ProductVariant, VariantOption, VariantPriceTier
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
SOLD_STATUSES = _SOLD_STATUSES
OPTION_PARAM_PREFIX = "opt_"


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


def annotate_pin(qs: QuerySet[Product], context) -> QuerySet[Product]:
    """Phase 16: stock at the stores serving the shopper's PIN (`pin_stock`) and at the stores that can
    deliver fast there now (`pin_fast_stock`). `context` is `apps.delivery.pin.PinContext` (or None)."""
    if context is None:
        return qs
    inventory = _fulfillment_inventory().filter(available_quantity__gt=0)
    return qs.annotate(
        pin_stock=_product_stock(inventory.filter(store_id__in=list(context.serving_store_ids))),
        pin_fast_stock=_product_stock(inventory.filter(store_id__in=list(context.fast_store_ids))),
    )


def _has_pin(qs: QuerySet[Product]) -> bool:
    return "pin_fast_stock" in qs.query.annotations


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
    # Phase 15 bulk pricing: the lowest tier price over active variants (None = no bulk price).
    tiers = VariantPriceTier.objects.filter(variant__product=OuterRef("pk"), variant__is_active=True).values(
        "variant__product"
    )
    bulk_price = tiers.annotate(best=Min("unit_price")).values("best")[:1]
    bulk_from = tiers.annotate(first=Min("min_quantity")).values("first")[:1]
    qs = qs.annotate(
        price=Subquery(cheapest.values("price")[:1]),
        mrp=Subquery(cheapest.values("mrp")[:1]),
        cheapest_variant_id=Subquery(cheapest.values("id")[:1]),
        variant_count=Coalesce(Subquery(variant_count, output_field=IntegerField()), Value(0)),
        stock_total=_product_stock(_fulfillment_inventory()),
        fast_stock=_product_stock(_fast_delivery_inventory()),
        sold_count=Coalesce(Subquery(sold, output_field=IntegerField()), Value(0)),
        bulk_min_price=Subquery(bulk_price),
        bulk_min_quantity=Subquery(bulk_from, output_field=IntegerField()),
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


def option_filters(params) -> dict[str, list[str]]:
    """`opt_<option-type-slug>=value-slug,…` → {type: [values]} (Phase 15 structured options)."""
    out = {}
    for name in params:
        if name.startswith(OPTION_PARAM_PREFIX) and (values := _csv(params.get(name))):
            out[name[len(OPTION_PARAM_PREFIX) :][:70]] = values
    return out


def category_scope(category: Category) -> set[int]:
    """The category and everything below it (up to three levels)."""
    from .tree import descendant_ids

    return descendant_ids(category.pk)


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
        scope = category_scope(category)
        qs = qs.filter(Q(category_id__in=scope) | Q(subcategory_id__in=scope))
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
        # With a PIN (Phase 16) "fast delivery" means fast to that PIN; without one, the Phase 4 meaning.
        if params.get("fast_delivery") in TRUE_VALUES:
            qs = qs.filter(pin_fast_stock__gt=0) if _has_pin(qs) else qs.filter(fast_stock__gt=0)
        if params.get("deliverable") in TRUE_VALUES and _has_pin(qs):
            qs = qs.filter(pin_stock__gt=0)
    if params.get("featured") in TRUE_VALUES:
        qs = qs.filter(is_featured=True)
    if params.get("bestseller") in TRUE_VALUES:
        qs = qs.filter(sold_count__gt=0)
    if params.get("bulk_pricing") in TRUE_VALUES:
        qs = qs.filter(bulk_min_price__isnull=False)
    if only := _csv(params.get("slugs")):  # Phase 16: recently viewed (max 20 slugs)
        qs = qs.filter(slug__in=only)
    if excluded := _csv(params.get("exclude")):
        qs = qs.exclude(slug__in=excluded)
    if "spec" not in skip:
        for key, values in spec_filters(params).items():
            value_q = Q()
            for value in values:
                value_q |= Q(value__iexact=value)
            qs = qs.filter(pk__in=ProductSpecification.objects.filter(value_q, key=key).values("product_id"))
    if "option" not in skip:
        for type_slug, values in option_filters(params).items():
            matching = VariantOption.objects.filter(
                option_type__slug=type_slug, value__slug__in=values, variant__is_active=True
            ).values("variant__product_id")
            qs = qs.filter(pk__in=matching)
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
    if category is not None:
        categories = _child_category_counts(category, ids_without("category"))
    else:
        category_rows = (
            Product.objects.filter(pk__in=ids_without("category"))
            .values("category__slug", "category__name")
            .annotate(count=Count("id"))
            .order_by("category__name")
        )
        categories = [
            {"slug": r["category__slug"], "name": r["category__name"], "count": r["count"]} for r in category_rows
        ]

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
            "fast_delivery": availability_base.filter(
                **({"pin_fast_stock__gt": 0} if _has_pin(availability_base) else {"fast_stock__gt": 0})
            ).count(),
        },
        "specifications": _spec_facets(ids_without("spec"), total_for_coverage=total, selected=spec_filters(params)),
        "options": _option_facets(ids_without("option"), selected=option_filters(params)),
    }


def _child_category_counts(category: Category, product_ids) -> list[dict]:
    """The selected category's direct children with how many of the results sit under each."""
    from .tree import descendant_ids, parent_map

    parents = parent_map()
    children = list(Category.objects.filter(parent=category, is_active=True).order_by("sort_order", "name"))
    if not children:
        return []
    rows = list(Product.objects.filter(pk__in=product_ids).values_list("category_id", "subcategory_id"))
    out = []
    for child in children:
        scope = descendant_ids(child.pk, parents)
        count = sum(1 for cat, sub in rows if cat in scope or sub in scope)
        if count:
            out.append({"slug": child.slug, "name": child.name, "count": count})
    return out


def _option_facets(product_ids, *, selected: dict[str, list[str]]) -> list[dict]:
    """Structured option values (Grade, Bag size, …) with product counts, for Phase 16 filters."""
    rows = (
        VariantOption.objects.filter(variant__product_id__in=product_ids, variant__is_active=True)
        .values(
            "option_type__slug",
            "option_type__name",
            "option_type__sort_order",
            "value__slug",
            "value__value",
            "value__sort_order",
        )
        .annotate(count=Count("variant__product_id", distinct=True))
    )
    by_type: dict[str, dict] = {}
    for row in rows:
        entry = by_type.setdefault(
            row["option_type__slug"],
            {
                "slug": row["option_type__slug"],
                "name": row["option_type__name"],
                "order": row["option_type__sort_order"],
                "values": [],
            },
        )
        entry["values"].append(
            {
                "slug": row["value__slug"],
                "value": row["value__value"],
                "count": row["count"],
                "order": row["value__sort_order"],
            }
        )
    facets = []
    for entry in sorted(by_type.values(), key=lambda e: (e["order"], e["name"])):
        if len(entry["values"]) < 2 and entry["slug"] not in selected:
            continue
        entry["values"].sort(key=lambda v: (v["order"], v["value"]))
        values = [{"slug": v["slug"], "value": v["value"], "count": v["count"]} for v in entry["values"]]
        facets.append({"slug": entry["slug"], "name": entry["name"], "values": values})
    return facets


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


def variant_fast_delivery_ids(variant_ids, pin=None) -> set[int]:
    """Variants in stock at a fast-delivery store; with a PIN context, at a store fast to that PIN."""
    if pin is not None:
        inventory = _fulfillment_inventory().filter(store_id__in=list(pin.fast_store_ids), available_quantity__gt=0)
    else:
        inventory = _fast_delivery_inventory()
    return set(inventory.filter(variant_id__in=list(variant_ids)).values_list("variant_id", flat=True))


def variant_ids_at_stores(variant_ids, store_ids) -> set[int]:
    """Variants in stock at any of `store_ids` (the stores serving a PIN)."""
    rows = _fulfillment_inventory().filter(
        variant_id__in=list(variant_ids), store_id__in=list(store_ids), available_quantity__gt=0
    )
    return set(rows.values_list("variant_id", flat=True))


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
