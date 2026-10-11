"""Catalog write workflows (admin) and customer search history."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.exceptions import ConflictError, ServiceError

from .models import (
    Category,
    OptionType,
    OptionValue,
    Product,
    ProductSpecification,
    ProductVariant,
    RecentSearch,
    VariantOption,
    VariantPriceTier,
)
from .search import normalize_query
from .tree import lineage


class CatalogRuleError(ServiceError):
    default_code = "invalid_catalog_data"


@transaction.atomic
def save_product(*, instance: Product | None, data: dict, actor=None) -> Product:
    """Create/update a product with its variants (upsert) and specifications (replace-all).

    Each variant may carry `price_tiers` (replace-all, Phase 15) and `options` (replace-all).
    Every rule is checked again after all variants are saved, so a price change that would make
    an existing tier dearer than the normal price is refused, and two variants can't share options.
    """
    variants = data.pop("variants", None)
    specs = data.pop("specifications", None)
    accessories = data.pop("accessories", None)

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
    if accessories is not None:
        set_accessories(product, accessories)
    _ensure_single_default_variant(product)
    _check_product_rules(product)
    return product


def relation_rows(product: Product) -> list[dict]:
    """The product's links as {product, kind, note}, in order (for the audit log and the dashboard)."""
    return [
        {"product": r.related_id, "kind": r.kind, "note": r.note}
        for r in product.relations.order_by("sort_order", "id")
    ]


@transaction.atomic
def set_accessories(product: Product, rows: list[dict]) -> None:
    """Replace the product's links with `rows` = [{product: id, note, kind}] in order. Kinds (Phase 21): accessory
    (Phase 16 "goes with"), compatible, required, alternative, incompatible. A product is linked once."""
    from .models import ProductRelation

    kinds = set(ProductRelation.Kind.values)
    wanted = []
    for row in rows:
        related_id = row["product"]
        if related_id == product.pk:
            raise ServiceError("A product can't be linked to itself.", code="invalid_accessory")
        if related_id in (w[0] for w in wanted):
            continue
        kind = row.get("kind") or ProductRelation.Kind.ACCESSORY
        if kind not in kinds:
            raise ServiceError(f"Unknown link type {kind}.", code="invalid_accessory")
        wanted.append((related_id, (row.get("note") or "")[:120], kind))
    found = set(Product.objects.filter(pk__in=[w[0] for w in wanted]).values_list("pk", flat=True))
    if missing := [w[0] for w in wanted if w[0] not in found]:
        raise ServiceError(f"Unknown accessory product {missing[0]}.", code="invalid_accessory")
    Product.objects.select_for_update().filter(pk=product.pk).first()  # one editor at a time
    product.relations.all().delete()
    ProductRelation.objects.bulk_create(
        [
            ProductRelation(product=product, related_id=related_id, note=note, kind=kind, sort_order=order)
            for order, (related_id, note, kind) in enumerate(wanted)
        ]
    )


def _upsert_variants(product: Product, variants: list[dict]) -> None:
    for position, data in enumerate(variants):
        tiers = data.pop("price_tiers", None)
        options = data.pop("options", None)
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
        if options is not None:
            set_variant_options(variant, options)
        if tiers is not None:
            set_price_tiers(variant, tiers)


# --- Bulk price tiers (Phase 15) -----------------------------------------------------------------


def validate_price_tiers(variant: ProductVariant, tiers: list[dict]) -> list[tuple[int, Decimal]]:
    """Check a complete tier list for one variant; returns [(min_quantity, unit_price)] sorted.

    - min_quantity: a whole number ≥ 2, at most the product's order limit, not repeated
      (tiers are "from N units", so a repeated N is an overlapping range)
    - unit_price: more than 0, at most the MRP, lower than the normal price and lower than every
      tier for fewer units (buying more never costs more per unit)
    """
    rows = []
    for index, tier in enumerate(tiers, start=1):
        try:
            quantity = int(tier["min_quantity"])
            price = Decimal(str(tier["unit_price"])).quantize(Decimal("0.01"))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise CatalogRuleError(f"Tier {index}: enter a quantity and a price.", code="invalid_tier") from None
        if not price.is_finite():
            raise CatalogRuleError(f"Tier {index}: enter a quantity and a price.", code="invalid_tier")
        if quantity < 2:
            raise CatalogRuleError(f"Tier {index}: bulk prices start from 2 units.", code="invalid_tier")
        if price <= 0:
            raise CatalogRuleError(f"Tier {index}: the price must be more than ₹0.", code="invalid_tier")
        rows.append((quantity, price))
    rows.sort()
    limit = variant.product.max_order_quantity
    previous_price, previous_qty = variant.price, 1
    for quantity, price in rows:
        if quantity == previous_qty:
            raise CatalogRuleError(
                f"Two tiers start at {quantity} units; tier ranges can't overlap.", code="overlapping_tiers"
            )
        if quantity > limit:
            raise CatalogRuleError(
                f"The {quantity}+ tier can never be reached: customers can order at most {limit}.",
                code="tier_above_order_limit",
            )
        if price > variant.mrp:
            raise CatalogRuleError(
                f"The {quantity}+ price ₹{price} is above the MRP ₹{variant.mrp}.", code="tier_above_mrp"
            )
        if price >= previous_price:
            raise CatalogRuleError(
                f"The {quantity}+ price ₹{price} must be lower than ₹{previous_price} for fewer units.",
                code="tier_not_cheaper",
            )
        previous_price, previous_qty = price, quantity
    return rows


def set_price_tiers(variant: ProductVariant, tiers: list[dict]) -> list[VariantPriceTier]:
    rows = validate_price_tiers(variant, tiers)
    variant.price_tiers.all().delete()
    return VariantPriceTier.objects.bulk_create(
        [VariantPriceTier(variant=variant, min_quantity=quantity, unit_price=price) for quantity, price in rows]
    )


# --- Options (Phase 15) --------------------------------------------------------------------------


def option_types_for(product: Product) -> list[OptionType]:
    """Active option types offered for the product's category (or everywhere)."""
    product_lineage = lineage((product.category_id, product.subcategory_id))
    allowed = []
    for option_type in OptionType.objects.filter(is_active=True).prefetch_related("categories"):
        scope = {c.id for c in option_type.categories.all()}
        if not scope or scope & product_lineage:
            allowed.append(option_type)
    return allowed


def set_variant_options(variant: ProductVariant, options: list[dict]) -> None:
    """Replace a variant's options. Each entry: {"option_type": id, "value": "53 Grade"} (a new value
    is added to the option type) or {"option_type": id, "value_id": id}."""
    allowed = {t.id: t for t in option_types_for(variant.product)}
    chosen: dict[int, OptionValue] = {}
    for entry in options:
        type_id = str(entry.get("option_type") or "")
        option_type = allowed.get(int(type_id)) if type_id.isdigit() else None
        if option_type is None:
            raise CatalogRuleError("Choose an option that is used for this product's category.", code="invalid_option")
        if option_type.id in chosen:
            raise CatalogRuleError(f"'{option_type.name}' is set twice for one variant.", code="duplicate_option")
        if entry.get("value_id"):
            value = OptionValue.objects.filter(pk=entry["value_id"], option_type=option_type).first()
            if value is None:
                raise CatalogRuleError(
                    f"That value isn't one of the '{option_type.name}' values.", code="invalid_option"
                )
        else:
            text = " ".join(str(entry.get("value") or "").split())[:80]
            if not text:
                raise CatalogRuleError(f"Enter a value for '{option_type.name}'.", code="invalid_option")
            slug = slugify(text)[:90] or "value"
            value = OptionValue.objects.filter(option_type=option_type, slug=slug).first()
            if value is None:
                value = OptionValue.objects.create(
                    option_type=option_type, value=text, slug=slug, sort_order=option_type.values.count()
                )
        chosen[option_type.id] = value
    variant.option_values.all().delete()
    VariantOption.objects.bulk_create(
        [VariantOption(variant=variant, option_type_id=type_id, value=value) for type_id, value in chosen.items()]
    )
    # `attributes` stays the display copy older screens read (option names → values).
    names = {t.name for t in allowed.values()}
    attributes = {k: v for k, v in (variant.attributes or {}).items() if k not in names}
    attributes.update({allowed[type_id].name: value.value for type_id, value in chosen.items()})
    if attributes != variant.attributes:
        ProductVariant.objects.filter(pk=variant.pk).update(attributes=attributes)
        variant.attributes = attributes


def _check_product_rules(product: Product) -> None:
    """Rules across all variants of a product, after a save."""
    variants = list(product.variants.filter(is_active=True).prefetch_related("price_tiers", "option_values"))
    if product.is_published and not variants:
        # A draft may wait for its verified price (e.g. created from product photos); a live product may not.
        raise CatalogRuleError(
            "Add at least one active variant with its MRP and price before publishing.", code="no_priced_variant"
        )
    for variant in variants:
        tiers = [{"min_quantity": t.min_quantity, "unit_price": t.unit_price} for t in variant.price_tiers.all()]
        if tiers:
            validate_price_tiers(variant, tiers)
    seen: dict[frozenset, ProductVariant] = {}
    for variant in variants:
        combo = frozenset((o.option_type_id, o.value_id) for o in variant.option_values.all())
        if not combo:
            continue
        if combo in seen:
            raise CatalogRuleError(
                f"Variants {seen[combo].sku} and {variant.sku} have the same options; each variant needs its own.",
                code="duplicate_variant_options",
            )
        seen[combo] = variant


def resolve_variant(product: Product, wanted: dict[str, str]) -> ProductVariant:
    """The active variant with exactly these options ({option_type_slug: value_slug}).
    Unknown options, values or combinations are refused (`invalid_option`)."""
    variants = list(
        product.variants.filter(is_active=True).prefetch_related("option_values__option_type", "option_values__value")
    )
    used_types = {o.option_type.slug for v in variants for o in v.option_values.all()}
    unknown = sorted(set(wanted) - used_types)
    if unknown or not wanted:
        raise CatalogRuleError("Choose the product's options.", code="invalid_option", details={"unknown": unknown})
    for variant in variants:
        options = {o.option_type.slug: o.value.slug for o in variant.option_values.all()}
        if options == wanted:
            return variant
    raise CatalogRuleError("This combination of options isn't available.", code="invalid_option")


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
    if category.children.filter(is_deleted=False).exists():
        raise ConflictError("Remove or move its subcategories first.", code="category_has_children")
    if Product.objects.filter(category=category).exists() or Product.objects.filter(subcategory=category).exists():
        raise ConflictError("Move its products to another category first.", code="category_has_products")
    category.delete()  # soft delete


# --- Product pictures ----------------------------------------------------------------------------

MAX_IMAGES_PER_PRODUCT = 12


@transaction.atomic
def add_product_image(product: Product, file, *, variant=None, alt_text="", is_primary=False, **source):
    """Store one picture for a product (optionally for one of its variants) through the media storage.

    The first picture becomes the primary one; a new primary picture demotes the others. `source` takes
    the ProductImage provenance fields (source_type, image_type, source_url, licence). Used by the
    dashboard upload and by `manage.py import_product_images`.
    """
    from .models import ProductImage

    if variant is not None and variant.product_id != product.pk:
        raise ServiceError("That variant does not belong to this product.", code="invalid_variant")
    if product.is_published and source.get("source_type") == ProductImage.SourceType.UNVERIFIED:
        raise ServiceError(
            "A live product can't show an unverified picture. Unpublish it first or record the picture's source.",
            code="unverified_image",
        )
    count = product.images.count()
    if count >= MAX_IMAGES_PER_PRODUCT:
        raise ServiceError(f"A product can have at most {MAX_IMAGES_PER_PRODUCT} pictures.", code="too_many_images")
    image = ProductImage(
        product=product,
        variant=variant,
        image=file,
        alt_text=(alt_text or "")[:200],
        is_primary=is_primary or count == 0,
        sort_order=count,
        **source,
    )
    image.full_clean(exclude=["product", "variant"])  # extension and size validators
    image.save()
    if image.is_primary:
        product.images.exclude(pk=image.pk).update(is_primary=False)
    return image
