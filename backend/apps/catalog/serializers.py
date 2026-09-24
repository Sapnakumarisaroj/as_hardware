from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Brand, Category, Product, ProductImage, ProductSpecification, ProductVariant, RecentSearch
from .selectors import stock_status

# --- Categories & brands -----------------------------------------------------------


class _ProductCountMixin:
    def get_product_count(self, obj) -> int | None:
        # Annotated by the category views (published, active products); absent on writes.
        return getattr(obj, "product_count", None)


class SubCategorySerializer(_ProductCountMixin, serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "image", "sort_order", "product_count"]


class _ParentRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class CategorySerializer(_ProductCountMixin, serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()
    parent_detail = _ParentRefSerializer(source="parent", read_only=True, allow_null=True)

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
        ]
        extra_kwargs = {"slug": {"required": False}}

    def get_children(self, obj) -> list[dict]:
        children = [c for c in obj.children.all() if c.is_active and not c.is_deleted]
        return SubCategorySerializer(children, many=True, context=self.context).data

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


class ProductVariantSerializer(serializers.ModelSerializer):
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    available_quantity = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    fast_delivery = serializers.SerializerMethodField()

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
        ]

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
        ]

    def get_offer(self, obj) -> dict | None:
        """The live automatic offer for this product (badge only; the discount is applied in the cart)."""
        from apps.offers.engine import best_offer_for_product, load_active_offers

        # One offers query per response, shared by every product in a list (context is shared).
        if "active_offers" not in self.context:
            self.context["active_offers"] = load_active_offers()
        rule = best_offer_for_product(obj, self.context["active_offers"])
        if rule is None:
            return None
        return {
            "id": rule.id,
            "name": rule.name,
            "badge": rule.badge,
            "min_order_value": str(rule.min_order_value),
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

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + [
            "description",
            "tags",
            "gst_rate",
            "hsn_code",
            "max_order_quantity",
            "is_returnable",
            "variants",
            "specifications",
            "images",
        ]

    def get_variants(self, obj) -> list[dict]:
        variants = [v for v in obj.variants.all() if v.is_active]
        return ProductVariantSerializer(variants, many=True, context=self.context).data


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


class VariantWriteSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

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
        if category and category.parent_id:
            raise serializers.ValidationError({"category": "Choose a top-level category."})
        if subcategory and subcategory.parent_id != getattr(category, "id", None):
            raise serializers.ValidationError({"subcategory": "Subcategory must belong to the selected category."})
        return attrs
