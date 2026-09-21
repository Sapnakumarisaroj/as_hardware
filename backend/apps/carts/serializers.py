from rest_framework import serializers

from apps.catalog.serializers import ProductListSerializer


class TotalsSerializer(serializers.Serializer):
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)
    mrp_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    delivery_fee = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    grand_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    savings_vs_mrp = serializers.DecimalField(max_digits=12, decimal_places=2)


class CartLineSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="item.id")
    variant_id = serializers.IntegerField(source="item.variant.id")
    sku = serializers.CharField(source="item.variant.sku")
    product_id = serializers.IntegerField(source="item.variant.product.id")
    product_name = serializers.CharField(source="item.variant.product.name")
    product_slug = serializers.CharField(source="item.variant.product.slug")
    variant_name = serializers.CharField(source="item.variant.name")
    quantity = serializers.IntegerField(source="item.quantity")
    unit_price = serializers.DecimalField(source="item.variant.price", max_digits=12, decimal_places=2)
    unit_mrp = serializers.DecimalField(source="item.variant.mrp", max_digits=12, decimal_places=2)
    price_at_add = serializers.DecimalField(source="item.price_at_add", max_digits=12, decimal_places=2)
    price_changed = serializers.BooleanField()
    line_total = serializers.SerializerMethodField()
    available_quantity = serializers.IntegerField()
    in_stock = serializers.BooleanField()
    purchasable = serializers.BooleanField()

    def get_line_total(self, obj) -> str | None:
        return str(obj.priced.line_total) if obj.priced else None


class CartSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="cart.id")
    items = CartLineSerializer(source="lines", many=True)
    totals = TotalsSerializer()
    issues = serializers.ListField(child=serializers.CharField())
    can_checkout = serializers.BooleanField()


class AddCartItemSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=1000, default=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=1000)


class CouponPreviewRequestSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30)


class CouponPreviewSerializer(serializers.Serializer):
    code = serializers.CharField()
    description = serializers.CharField()
    discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    totals = TotalsSerializer()


class WishlistItemSerializer(serializers.Serializer):
    product = ProductListSerializer()
    added_at = serializers.DateTimeField(source="created_at")


class AddWishlistItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
