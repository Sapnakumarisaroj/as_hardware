"""Product comparison: GET /api/products/compare/?slugs=a,b,c (public, read-only).

Up to `MAX_COMPARE` published, active products side by side. Prices come from each product's
default variant (the active `is_default` one, else the cheapest active one). Specifications are
merged into rows keyed by spec key: one value per product ("—" when a product doesn't have it) and a
`differs` flag when the values aren't all the same. Only customer-facing fields are returned (never
cost price, SKUs of inactive variants, demo flags or other internal data).
"""

from decimal import Decimal

from django.db.models import Prefetch
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors
from .models import ProductSpecification, ProductVariant
from .tree import ancestor_ids, parent_map

MAX_COMPARE = 4
MISSING = "—"


def _money(value) -> str | None:
    return None if value is None else str(Decimal(value).quantize(Decimal("0.01")))


def _parse_slugs(raw: str | None) -> list[str]:
    seen: list[str] = []
    for part in (raw or "").split(","):
        slug = part.strip()[:220]
        if slug and slug not in seen:
            seen.append(slug)
    return seen


def _default_variant(product) -> ProductVariant | None:
    variants = list(product.active_variants)
    if not variants:
        return None
    for variant in variants:
        if variant.is_default:
            return variant
    return min(variants, key=lambda v: (v.price, v.pk))


def _department(product, parents) -> dict | None:
    """The top-level category the product sits under."""
    chain = ancestor_ids(product.category_id, parents)
    if not chain:
        return None
    top_id = chain[-1]
    category = product.category
    while category is not None and category.pk != top_id:
        category = category.parent
    return {"id": top_id, "name": category.name if category else "", "slug": category.slug if category else ""}


def _spec_text(spec: ProductSpecification) -> str:
    value = (spec.value or "").strip()
    unit = (spec.unit or "").strip()
    if value and unit and not value.lower().endswith(unit.lower()):
        return f"{value} {unit}"
    return value or MISSING


def _image_url(product, request) -> tuple[str | None, str]:
    images = list(product.images.all())  # primary first (model ordering)
    if not images:
        return None, product.name
    image = images[0]
    url = image.image.url
    return (request.build_absolute_uri(url) if request else url), (image.alt_text or product.name)[:200]


def _product_payload(product, request, parents) -> dict:
    variant = _default_variant(product)
    price = variant.price if variant else None
    mrp = variant.mrp if variant else None
    discount = None
    if price is not None and mrp:
        discount = _money((mrp - price) * 100 / mrp) if mrp > price else "0.00"
    image, image_alt = _image_url(product, request)
    return {
        "id": product.pk,
        "name": product.name,
        "slug": product.slug,
        "brand": {"name": product.brand.name, "slug": product.brand.slug} if product.brand else None,
        "category": {"name": product.category.name, "slug": product.category.slug},
        "department": _department(product, parents),
        "image": image,
        "image_alt": image_alt,
        "unit": product.unit,
        "unit_label": product.get_unit_display(),
        "default_variant_id": variant.pk if variant else None,
        "variant_name": variant.name if variant else "",
        "price": _money(price),
        "mrp": _money(mrp),
        "discount_percent": discount,
        "stock_status": selectors.stock_status(getattr(product, "stock_total", 0)),
        "rating_avg": _money(product.rating_avg) if product.rating_count else None,
        "rating_count": product.rating_count,
    }


def _spec_rows(products) -> list[dict]:
    """Merge every product's specs into rows ordered by first appearance (product order, then the
    product's own spec order)."""
    rows: dict[str, dict] = {}
    for index, product in enumerate(products):
        for spec in product.specifications.all():
            key = spec.key or spec.name.strip().lower()
            row = rows.setdefault(key, {"key": key, "name": spec.name, "values": [MISSING] * len(products)})
            if row["values"][index] == MISSING:
                row["values"][index] = _spec_text(spec)
    out = []
    for row in rows.values():
        normalised = {value.strip().lower() for value in row["values"]}
        row["differs"] = len(normalised) > 1
        out.append(row)
    return out


def compare_data(slugs: list[str], request=None) -> dict:
    qs = (
        selectors.product_queryset()
        .select_related("category__parent")
        .prefetch_related(
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.filter(is_active=True).order_by("sort_order", "id"),
                to_attr="active_variants",
            ),
            Prefetch("specifications", queryset=ProductSpecification.objects.order_by("sort_order", "id")),
        )
        .filter(slug__in=slugs)
    )
    found = {p.slug: p for p in qs}
    products = [found[slug] for slug in slugs if slug in found]
    parents = parent_map() if products else {}
    payload = [_product_payload(p, request, parents) for p in products]
    departments = {item["department"]["id"] for item in payload if item["department"]}
    return {
        "products": payload,
        "specifications": _spec_rows(products),
        "missing": [slug for slug in slugs if slug not in found],
        "mixed_departments": len(departments) > 1,
        "max_products": MAX_COMPARE,
    }


class ProductCompareView(APIView):
    """`?slugs=a,b,c` — up to four product slugs, in the order to show them."""

    permission_classes = [AllowAny]

    def get(self, request):
        slugs = _parse_slugs(request.query_params.get("slugs"))
        if not slugs:
            return Response({"detail": "Pass one or more product slugs as ?slugs=a,b."}, status=400)
        if len(slugs) > MAX_COMPARE:
            return Response({"detail": f"Compare up to {MAX_COMPARE} products at a time."}, status=400)
        return Response(compare_data(slugs, request))
