"""Catalog write workflows (admin) and customer search history."""

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.exceptions import ConflictError, ServiceError

from .models import Category, Product, ProductSpecification, ProductVariant, RecentSearch
from .search import normalize_query


@transaction.atomic
def save_product(*, instance: Product | None, data: dict, actor=None) -> Product:
    """Create/update a product with its variants (upsert) and specifications (replace-all)."""
    variants = data.pop("variants", None)
    specs = data.pop("specifications", None)

    product = instance or Product()
    for field, value in data.items():
        setattr(product, field, value)
    product.full_clean(exclude=["slug"] if not product.slug else None)
    product.save()

    if variants is not None:
        _upsert_variants(product, variants)
    if specs is not None:
        product.specifications.all().delete()
        seen = set()
        for order, spec in enumerate(specs):
            key = slugify(spec["name"])
            if key in seen:
                raise ServiceError(f"Duplicate specification '{spec['name']}'.", code="duplicate_specification")
            seen.add(key)
            ProductSpecification.objects.create(
                product=product, name=spec["name"], value=spec["value"], unit=spec.get("unit", ""), sort_order=order
            )
    _ensure_single_default_variant(product)
    return product


def _upsert_variants(product: Product, variants: list[dict]) -> None:
    for position, data in enumerate(variants):
        variant_id = data.pop("id", None)
        if variant_id:
            variant = ProductVariant.objects.filter(pk=variant_id, product=product).first()
            if variant is None:
                raise ServiceError(f"Variant {variant_id} does not belong to this product.", code="invalid_variant")
        else:
            variant = ProductVariant(product=product, sort_order=position)
        clash = ProductVariant.objects.filter(sku=data.get("sku", variant.sku)).exclude(pk=variant.pk).exists()
        if clash:
            raise ConflictError(f"SKU '{data['sku']}' is already used by another variant.", code="duplicate_sku")
        for field, value in data.items():
            setattr(variant, field, value)
        variant.full_clean(exclude=["product"])
        variant.save()


def _ensure_single_default_variant(product: Product) -> None:
    active = list(product.variants.filter(is_active=True).order_by("sort_order", "id"))
    defaults = [v for v in active if v.is_default]
    keep = defaults[0] if defaults else (active[0] if active else None)
    product.variants.exclude(pk=getattr(keep, "pk", None)).filter(is_default=True).update(is_default=False)
    if keep and not keep.is_default:
        ProductVariant.objects.filter(pk=keep.pk).update(is_default=True)


def record_recent_search(user, query: str) -> RecentSearch | None:
    """Remember a customer's search (newest first, at most RecentSearch.MAX_PER_USER kept)."""
    query = normalize_query(query)
    if len(query) < 2:
        return None
    # Re-insert rather than update, so a repeated search also gets the newest id: the clock can
    # return the same timestamp for quick successive searches (coarse timers on Windows), and
    # `-id` is the ordering tie-breaker.
    with transaction.atomic():
        RecentSearch.objects.filter(user=user, normalized=query.lower()).delete()
        entry = RecentSearch.objects.create(
            user=user, query=query, normalized=query.lower(), searched_at=timezone.now()
        )
    stale = RecentSearch.objects.filter(user=user).values_list("pk", flat=True)[RecentSearch.MAX_PER_USER :]
    RecentSearch.objects.filter(pk__in=list(stale)).delete()
    return entry


def delete_category(category: Category) -> None:
    if category.children.exists():
        raise ConflictError("Remove or move its subcategories first.", code="category_has_children")
    if Product.objects.filter(category=category).exists() or Product.objects.filter(subcategory=category).exists():
        raise ConflictError("Move its products to another category first.", code="category_has_products")
    category.delete()  # soft delete
