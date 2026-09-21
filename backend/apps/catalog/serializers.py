from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Brand, Category, Product, ProductImage, ProductSpecification, ProductVariant
from .selectors import stock_status

# --- Categories & brands -----------------------------------------------------------


class SubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "image", "sort_order"]


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "description", "image", "sort_order", "is_active", "children"]
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
    available_quantity = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()

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
            "weight_grams",
            "length_mm",
            "width_mm",
            "height_mm",
            "is_default",
            "available_quantity",
            "stock_status",
        ]

    def get_available_quantity(self, obj) -> int:
        return self.context.get("stock_map", {}).get(obj.id, 0)

    def get_stock_status(self, obj) -> str:
        return stock_status(self.get_available_quantity(obj))


class ProductListSerializer(serializers.ModelSerializer):
    brand = _NamedRefSerializer(allow_null=True)
    category = _NamedRefSerializer()
    subcategory = _NamedRefSerializer(allow_null=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    mrp = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    discount_percent = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

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
            "stock_status",
            "is_featured",
            "rating_avg",
            "rating_count",
            "image",
        ]

    def get_discount_percent(self, obj) -> str | None:
        # String like every other decimal in the API (never float).
        if not getattr(obj, "mrp", None) or obj.price is None:
            return None
        return str(((obj.mrp - obj.price) * 100 / obj.mrp).quantize(Decimal("0.01")))

    def get_stock_status(self, obj) -> str:
        return stock_status(getattr(obj, "stock_total", 0))

    def get_image(self, obj) -> str | None:
        images = list(obj.images.all())
        if not images:
            return None
        request = self.context.get("request")
        url = images[0].image.url
        return request.build_absolute_uri(url) if request else url


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
