from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    Brand,
    Category,
    Collection,
    OptionType,
    Product,
    ProductImage,
    ProductSpecification,
    ProductVariant,
    RecentSearch,
)
from .selectors import stock_status

# --- Categories & brands -----------------------------------------------------------


class _ProductCountMixin:
    def get_product_count(self, obj) -> int | None:
        # Annotated by the category views (published, active products); absent on writes.
        return getattr(obj, "product_count", None)


class SubCategorySerializer(_ProductCountMixin, serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "image", "sort_order", "product_count", "children"]

    def get_children(self, obj) -> list[dict]:
        """Third level (Phase 15), e.g. Cement › Grey Cement. Empty for the deepest level."""
        counts = self.context.get("category_counts", {})
        rows = []
        for child in self.context.get("grandchildren", {}).get(obj.pk, []):
            rows.append(
                {
                    "id": child.pk,
                    "name": child.name,
                    "slug": child.slug,
                    "description": child.description,
                    "image": child.image.url if child.image else None,
                    "sort_order": child.sort_order,
                    "product_count": counts.get(child.pk),
                    "children": [],
                }
            )
        return rows


class _ParentRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class CategorySerializer(_ProductCountMixin, serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    parent_detail = _ParentRefSerializer(source="parent", read_only=True, allow_null=True)
    level = serializers.SerializerMethodField()
    breadcrumb = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "parent",
            "parent_detail",
            "description",
            "image",
            "sort_order",
            "is_active",
            "product_count",
            "children",
            "level",
            "breadcrumb",
        ]
        extra_kwargs = {"slug": {"required": False}}

    def get_children(self, obj) -> list[dict]:
        children = [c for c in obj.children.all() if c.is_active and not c.is_deleted]
        return SubCategorySerializer(children, many=True, context=self.context).data

    def get_level(self, obj) -> int:
        return len(self.get_breadcrumb(obj))

    def get_breadcrumb(self, obj) -> list[dict]:
        """From the department down to this category: [{id, name, slug}]."""
        from .tree import breadcrumb

        return [{"id": c.pk, "name": c.name, "slug": c.slug} for c in breadcrumb(obj)]

    def validate(self, attrs):
        instance = self.instance or Category()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "logo", "description", "is_active"]
        extra_kwargs = {"slug": {"required": False}}


class _NamedRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()


# --- Products (read) ------------------------------------------------------------------


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "variant", "is_primary", "sort_order"]


class ProductSpecificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSpecification
        fields = ["name", "key", "value", "unit", "sort_order"]
        read_only_fields = ["key"]


def tier_rows(variant) -> list[dict]:
    """Bulk price table for a variant: the normal price first, then each tier, with its range."""
    from apps.orders.pricing import price_tiers

    tiers = price_tiers(variant)
    if not tiers:
        return []
    starts = [1] + [m for m, _ in tiers]
    prices = [variant.price] + [p for _, p in tiers]
    rows = []
    for index, (start, price) in enumerate(zip(starts, prices, strict=True)):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else None
        saving = (variant.price - price) * 100 / variant.price if variant.price else Decimal(0)
        rows.append(
            {
                "min_quantity": start,
                "max_quantity": end,
                "unit_price": _money(price),
                "saving_percent": _money(saving),
                "is_base": index == 0,
            }
        )
    return rows


class ProductVariantSerializer(serializers.ModelSerializer):
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    available_quantity = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    fast_delivery = serializers.SerializerMethodField()
    price_tiers = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "name",
            "attributes",
            "mrp",
            "price",
            "discount_percent",
            "discount_amount",
            "weight_grams",
            "length_mm",
            "width_mm",
            "height_mm",
            "is_default",
            "available_quantity",
            "stock_status",
            "fast_delivery",
            "price_tiers",
            "options",
        ]

    def get_price_tiers(self, obj) -> list[dict]:
        """Bulk prices (Phase 15): [{min_quantity, max_quantity|null, unit_price, saving_percent, is_base}].
        Display only: the cart and checkout calculate the price charged."""
        return tier_rows(obj)

    def get_options(self, obj) -> dict:
        """{option_type_slug: value_slug} — which option values this variant is."""
        return {o.option_type.slug: o.value.slug for o in obj.option_values.all()}

    def _stock(self, obj) -> int:
        return self.context.get("stock_map", {}).get(obj.id, 0)

    def get_available_quantity(self, obj) -> int | None:
        # Exact counts are internal; customers only see "only N left" when stock is low.
        total = self._stock(obj)
        return total if stock_status(total) == "low_stock" else None

    def get_stock_status(self, obj) -> str:
        return stock_status(self._stock(obj))

    def get_fast_delivery(self, obj) -> bool:
        return obj.id in self.context.get("fast_variant_ids", set())


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


class ProductListSerializer(serializers.ModelSerializer):
    brand = _NamedRefSerializer(allow_null=True)
    category = _NamedRefSerializer()
    subcategory = _NamedRefSerializer(allow_null=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    mrp = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    discount_percent = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    fast_delivery = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()
    default_variant_id = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    image_alt = serializers.SerializerMethodField()
    offer = serializers.SerializerMethodField()
    bulk_pricing = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "sku",
            "short_description",
            "brand",
            "category",
            "subcategory",
            "unit",
            "price",
            "mrp",
            "discount_percent",
            "discount_amount",
            "stock_status",
            "fast_delivery",
            "variant_count",
            "default_variant_id",
            "is_featured",
            "rating_avg",
            "rating_count",
            "image",
            "image_alt",
            "offer",
            "bulk_pricing",
        ]

    def get_bulk_pricing(self, obj) -> dict | None:
        """Phase 15: {"from_quantity": 10, "lowest_unit_price": "395.00"} when any variant has bulk
        prices (from the listing annotation), else null. The price charged comes from the cart."""
        lowest = getattr(obj, "bulk_min_price", None)
        if lowest is None:
            return None
        return {"from_quantity": getattr(obj, "bulk_min_quantity", None), "lowest_unit_price": _money(lowest)}

    def get_offer(self, obj) -> dict | None:
        """The live automatic offer for this product (badge only; the discount is applied in the cart)."""
        from apps.offers.engine import best_offer_for_product, load_active_offers

        # One offers query per response, shared by every product in a list (context is shared).
        if "active_offers" not in self.context:
            from .tree import parent_map

            self.context["active_offers"] = load_active_offers()
            self.context["category_parents"] = parent_map() if self.context["active_offers"] else {}
        rule = best_offer_for_product(obj, self.context["active_offers"], self.context.get("category_parents"))
        if rule is None:
            return None
        return {
            "id": rule.id,
            "name": rule.name,
            "badge": rule.badge,
            "min_order_value": str(rule.min_order_value),
            "benefit": rule.benefit,
            "min_quantity": rule.min_quantity,
            "campaign": rule.campaign,
            "conditions": rule.conditions,
        }

    def _has_price(self, obj) -> bool:
        return bool(getattr(obj, "mrp", None)) and getattr(obj, "price", None) is not None

    def get_discount_percent(self, obj) -> str | None:
        # String like every other decimal in the API (never float).
        if not self._has_price(obj):
            return None
        return _money((obj.mrp - obj.price) * 100 / obj.mrp)

    def get_discount_amount(self, obj) -> str | None:
        return _money(obj.mrp - obj.price) if self._has_price(obj) else None

    def get_stock_status(self, obj) -> str:
        return stock_status(getattr(obj, "stock_total", 0))

    def get_fast_delivery(self, obj) -> bool:
        return getattr(obj, "fast_stock", 0) > 0

    def get_variant_count(self, obj) -> int:
        return getattr(obj, "variant_count", 0)

    def get_default_variant_id(self, obj) -> int | None:
        """The variant whose price is shown (cheapest active one)."""
        return getattr(obj, "cheapest_variant_id", None)

    def _primary_image(self, obj):
        images = list(obj.images.all())  # ordered primary-first
        return images[0] if images else None

    def get_image(self, obj) -> str | None:
        image = self._primary_image(obj)
        if image is None:
            return None
        request = self.context.get("request")
        url = image.image.url
        return request.build_absolute_uri(url) if request else url

    def get_image_alt(self, obj) -> str:
        image = self._primary_image(obj)
        return (image.alt_text if image and image.alt_text else obj.name)[:200]


class ProductDetailSerializer(ProductListSerializer):
    variants = serializers.SerializerMethodField()
    specifications = ProductSpecificationSerializer(many=True, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    options = serializers.SerializerMethodField()
    breadcrumb = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + [
            "description",
            "tags",
            "gst_rate",
            "hsn_code",
            "max_order_quantity",
            "is_returnable",
            "launch_date",
            "variants",
            "specifications",
            "images",
            "options",
            "breadcrumb",
        ]

    def get_variants(self, obj) -> list[dict]:
        variants = [v for v in obj.variants.all() if v.is_active]
        return ProductVariantSerializer(variants, many=True, context=self.context).data

    def get_options(self, obj) -> list[dict]:
        """Option types the active variants differ by, with the values that exist:
        [{slug, name, unit, values: [{slug, value}]}]. Empty for products without options."""
        types: dict[int, dict] = {}
        for variant in obj.variants.all():
            if not variant.is_active:
                continue
            for option in variant.option_values.all():
                kind = option.option_type
                entry = types.setdefault(
                    kind.pk,
                    {"slug": kind.slug, "name": kind.name, "unit": kind.unit, "order": kind.sort_order, "values": {}},
                )
                entry["values"][option.value.pk] = option.value
        rows = []
        for entry in sorted(types.values(), key=lambda e: (e["order"], e["name"])):
            values = sorted(entry["values"].values(), key=lambda v: (v.sort_order, v.value))
            rows.append(
                {
                    "slug": entry["slug"],
                    "name": entry["name"],
                    "unit": entry["unit"],
                    "values": [{"slug": v.slug, "value": v.value} for v in values],
                }
            )
        return rows

    def get_breadcrumb(self, obj) -> list[dict]:
        from .tree import breadcrumb

        deepest = obj.subcategory or obj.category
        return [{"id": c.pk, "name": c.name, "slug": c.slug} for c in breadcrumb(deepest)]


# --- Facets & search helpers --------------------------------------------------------------


class _FacetOptionSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    count = serializers.IntegerField()


class _ThresholdCountSerializer(serializers.Serializer):
    min = serializers.IntegerField()
    count = serializers.IntegerField()


class _SpecValueSerializer(serializers.Serializer):
    value = serializers.CharField()
    count = serializers.IntegerField()


class _SpecFacetSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    unit = serializers.CharField(allow_blank=True)
    values = _SpecValueSerializer(many=True)


class _PriceRangeSerializer(serializers.Serializer):
    min = serializers.CharField(allow_null=True)
    max = serializers.CharField(allow_null=True)


class _AvailabilityFacetSerializer(serializers.Serializer):
    in_stock = serializers.IntegerField()
    fast_delivery = serializers.IntegerField()


class _OptionValueFacetSerializer(serializers.Serializer):
    slug = serializers.CharField()
    value = serializers.CharField()
    count = serializers.IntegerField()


class _OptionFacetSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    values = _OptionValueFacetSerializer(many=True)


class ProductFacetsSerializer(serializers.Serializer):
    """Schema only (the view returns the selector's dict)."""

    total = serializers.IntegerField()
    categories = _FacetOptionSerializer(many=True)
    brands = _FacetOptionSerializer(many=True)
    price = _PriceRangeSerializer()
    ratings = _ThresholdCountSerializer(many=True)
    discounts = _ThresholdCountSerializer(many=True)
    availability = _AvailabilityFacetSerializer()
    specifications = _SpecFacetSerializer(many=True)
    options = _OptionFacetSerializer(many=True)


class _SuggestedCategorySerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    parent_name = serializers.CharField(allow_null=True)


class _SuggestedBrandSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()


class SearchSuggestionsSerializer(serializers.Serializer):
    query = serializers.CharField(allow_blank=True)
    products = serializers.ListField(child=serializers.DictField())
    categories = _SuggestedCategorySerializer(many=True)
    brands = _SuggestedBrandSerializer(many=True)


class RecentSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecentSearch
        fields = ["query", "searched_at"]
        read_only_fields = ["searched_at"]


# --- Products (admin write) -------------------------------------------------------------


class PriceTierWriteSerializer(serializers.Serializer):
    min_quantity = serializers.IntegerField(min_value=2, max_value=100000)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class VariantOptionWriteSerializer(serializers.Serializer):
    option_type = serializers.IntegerField(min_value=1)
    value = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    value_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class VariantWriteSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    price_tiers = PriceTierWriteSerializer(many=True, required=False)
    options = VariantOptionWriteSerializer(many=True, required=False)

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "name",
            "attributes",
            "mrp",
            "price",
            "weight_grams",
            "length_mm",
            "width_mm",
            "height_mm",
            "is_default",
            "is_active",
            "sort_order",
            "price_tiers",
            "options",
        ]
        extra_kwargs = {"sku": {"validators": []}}  # uniqueness checked in the service (upsert by id)

    def validate(self, attrs):
        if attrs.get("price") and attrs.get("mrp") and attrs["price"] > attrs["mrp"]:
            raise serializers.ValidationError({"price": "Selling price cannot exceed MRP."})
        return attrs


class SpecificationWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    value = serializers.CharField(max_length=200)
    unit = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")


class ProductWriteSerializer(serializers.ModelSerializer):
    variants = VariantWriteSerializer(many=True, required=False)
    specifications = SpecificationWriteSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = [
            "name",
            "slug",
            "sku",
            "brand",
            "category",
            "subcategory",
            "short_description",
            "description",
            "tags",
            "unit",
            "gst_rate",
            "hsn_code",
            "max_order_quantity",
            "is_active",
            "is_published",
            "is_featured",
            "is_returnable",
            "launch_date",
            "variants",
            "specifications",
        ]
        extra_kwargs = {"slug": {"required": False}}

    def validate_tags(self, value):
        if not isinstance(value, list) or not all(isinstance(t, str) and len(t) <= 50 for t in value):
            raise serializers.ValidationError("Tags must be a list of short strings.")
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("variants"):
            raise serializers.ValidationError({"variants": "At least one variant (SKU + price) is required."})
        category = attrs.get("category", getattr(self.instance, "category", None))
        subcategory = attrs.get("subcategory", getattr(self.instance, "subcategory", None))
        if category and category.level >= Category.MAX_DEPTH:
            raise serializers.ValidationError(
                {"category": "Choose a department or a category; put the most specific level in 'subcategory'."}
            )
        if subcategory and subcategory.parent_id != getattr(category, "id", None):
            raise serializers.ValidationError({"subcategory": "Subcategory must belong to the selected category."})
        return attrs


# --- Phase 15: options and curated lists ---------------------------------------------------------


class OptionTypeSerializer(serializers.ModelSerializer):
    values = serializers.SerializerMethodField()

    class Meta:
        model = OptionType
        fields = ["id", "name", "slug", "unit", "values"]

    def get_values(self, obj) -> list[dict]:
        return [{"id": v.pk, "value": v.value, "slug": v.slug} for v in obj.values.all()]


class CollectionSerializer(serializers.ModelSerializer):
    """A live curated list with its products (product cards as in the listing)."""

    products = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = ["id", "name", "slug", "description", "rule", "starts_at", "ends_at", "products"]

    def get_products(self, obj) -> list[dict]:
        rows = self.context.get("collection_products", {}).get(obj.pk, [])
        return ProductListSerializer(rows, many=True, context=self.context).data
