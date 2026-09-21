"""Read queries for the catalog. Price and stock are annotated with portable subqueries
(no vendor-specific SQL), so listing is a single query per page."""

from django.db.models import IntegerField, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.inventory.models import Inventory
from apps.stores.models import Store

from .models import Category, Product, ProductVariant

LOW_STOCK_DISPLAY_THRESHOLD = 5


def _fulfillment_inventory():
    return Inventory.objects.filter(
        is_active=True,
        store__is_active=True,
        store__is_deleted=False,
        store__accepts_orders=True,
        store__kind__in=Store.FULFILLMENT_KINDS,
    )


def annotate_listing(qs: QuerySet[Product]) -> QuerySet[Product]:
    cheapest = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True).order_by("price", "id")
    stock = (
        _fulfillment_inventory()
        .filter(variant__product=OuterRef("pk"), variant__is_active=True)
        .values("variant__product")
        .annotate(total=Sum("available_quantity"))
        .values("total")[:1]
    )
    return qs.annotate(
        price=Subquery(cheapest.values("price")[:1]),
        mrp=Subquery(cheapest.values("mrp")[:1]),
        stock_total=Coalesce(Subquery(stock, output_field=IntegerField()), Value(0)),
    )


def product_queryset(*, include_unpublished: bool = False) -> QuerySet[Product]:
    qs = Product.objects.select_related("brand", "category", "subcategory").prefetch_related("images")
    if not include_unpublished:
        qs = qs.filter(is_active=True, is_published=True)
    return annotate_listing(qs)


def filter_products(qs: QuerySet[Product], params) -> QuerySet[Product]:
    """Supported query params: category, subcategory, brand (comma list), min_price, max_price,
    in_stock, featured, q. Full-text/typo-tolerant search replaces `q` in Phase 4."""
    if slug := params.get("category"):
        category = Category.objects.filter(slug=slug).first()
        if category is None:
            return qs.none()
        qs = qs.filter(Q(category=category) | Q(subcategory=category))
    if slug := params.get("subcategory"):
        qs = qs.filter(subcategory__slug=slug)
    if brands := params.get("brand"):
        qs = qs.filter(brand__slug__in=[b.strip() for b in brands.split(",") if b.strip()])
    if (value := _decimal(params.get("min_price"))) is not None:
        qs = qs.filter(price__gte=value)
    if (value := _decimal(params.get("max_price"))) is not None:
        qs = qs.filter(price__lte=value)
    if params.get("in_stock") in ("1", "true", "yes"):
        qs = qs.filter(stock_total__gt=0)
    if params.get("featured") in ("1", "true", "yes"):
        qs = qs.filter(is_featured=True)
    if term := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(
            Q(name__icontains=term)
            | Q(sku__icontains=term)
            | Q(short_description__icontains=term)
            | Q(brand__name__icontains=term)
            | Q(variants__sku__icontains=term)
        ).distinct()
    return qs


ORDERINGS = {
    "price": ("price", "id"),
    "-price": ("-price", "id"),
    "newest": ("-created_at", "-id"),
    "name": ("name", "id"),
    "rating": ("-rating_avg", "-rating_count", "id"),
}


def order_products(qs: QuerySet[Product], ordering: str | None) -> QuerySet[Product]:
    return qs.order_by(*ORDERINGS.get(ordering or "", ("-is_featured", "name", "id")))


def variant_stock_map(variant_ids) -> dict[int, int]:
    rows = (
        _fulfillment_inventory()
        .filter(variant_id__in=list(variant_ids))
        .values("variant_id")
        .annotate(total=Sum("available_quantity"))
    )
    return {row["variant_id"]: row["total"] or 0 for row in rows}


def stock_status(total: int) -> str:
    if total <= 0:
        return "out_of_stock"
    if total <= LOW_STOCK_DISPLAY_THRESHOLD:
        return "low_stock"
    return "in_stock"


def _decimal(value):
    from decimal import Decimal, InvalidOperation

    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None
