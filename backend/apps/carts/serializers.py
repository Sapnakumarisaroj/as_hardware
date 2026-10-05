from decimal import Decimal

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
    offer_discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    coupon_discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    # Phase 15
    bulk_savings = serializers.DecimalField(max_digits=12, decimal_places=2)
    free_delivery = serializers.BooleanField()
    free_delivery_reason = serializers.CharField(allow_blank=True)
    amount_to_free_delivery = serializers.DecimalField(max_digits=12, decimal_places=2)
    free_delivery_threshold = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    free_delivery_hint = serializers.CharField(allow_blank=True, help_text='Items that count, e.g. "Cement"')
    # Phase 17: shop credit used (already deducted from grand_total)
    credit_discount = serializers.DecimalField(max_digits=12, decimal_places=2)


class AppliedOfferSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="offer.id")
    name = serializers.CharField(source="offer.name")
    description = serializers.CharField(source="offer.description")
    badge = serializers.CharField(source="offer.badge")
    discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    variant_ids = serializers.ListField(child=serializers.IntegerField())
    benefit = serializers.CharField(source="offer.benefit")
    campaign = serializers.CharField(source="offer.campaign")


class MissedOfferSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="offer.id")
    name = serializers.CharField(source="offer.name")
    badge = serializers.CharField(source="offer.badge")
    min_order_value = serializers.DecimalField(source="offer.min_order_value", max_digits=12, decimal_places=2)
    shortfall = serializers.DecimalField(max_digits=12, decimal_places=2)
    units_short = serializers.IntegerField(help_text="Quantity offers: units still needed on an item")
    min_quantity = serializers.IntegerField(source="offer.min_quantity")
    benefit = serializers.CharField(source="offer.benefit")


class CartOffersSerializer(serializers.Serializer):
    applied = AppliedOfferSerializer(many=True)
    missed = MissedOfferSerializer(many=True)
    free_delivery = AppliedOfferSerializer(allow_null=True)


class CartLineSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="item.id")
    variant_id = serializers.IntegerField(source="item.variant.id")
    sku = serializers.CharField(source="item.variant.sku")
    product_id = serializers.IntegerField(source="item.variant.product.id")
    product_name = serializers.CharField(source="item.variant.product.name")
    product_slug = serializers.CharField(source="item.variant.product.slug")
    variant_name = serializers.CharField(source="item.variant.name")
    quantity = serializers.IntegerField(source="item.quantity")
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, help_text="Per unit at this quantity (bulk tier applied)."
    )
    base_unit_price = serializers.DecimalField(
        source="item.variant.price", max_digits=12, decimal_places=2, help_text="Normal price for one unit."
    )
    bulk = serializers.SerializerMethodField()
    unit_mrp = serializers.DecimalField(source="item.variant.mrp", max_digits=12, decimal_places=2)
    price_at_add = serializers.DecimalField(source="item.price_at_add", max_digits=12, decimal_places=2)
    price_changed = serializers.BooleanField()
    line_total = serializers.SerializerMethodField()
    line_mrp_total = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    available_quantity = serializers.IntegerField()
    in_stock = serializers.BooleanField()
    purchasable = serializers.BooleanField()
    brand_name = serializers.CharField(source="item.variant.product.brand.name", default="")
    attributes = serializers.JSONField(source="item.variant.attributes")
    max_order_quantity = serializers.IntegerField(source="item.variant.product.max_order_quantity")
    image = serializers.SerializerMethodField()

    def get_line_total(self, obj) -> str | None:
        return str(obj.priced.line_total) if obj.priced else None

    def get_bulk(self, obj) -> dict | None:
        """Bulk pricing for this line: the tier applied, what it saves and the next cheaper tier.
        Null when the variant has no bulk prices."""
        priced = obj.priced
        if priced is None or (priced.tier_min_quantity is None and priced.next_tier is None):
            return None
        next_tier = None
        if priced.next_tier:
            min_quantity, price = priced.next_tier
            next_tier = {
                "min_quantity": min_quantity,
                "unit_price": str(price),
                "units_more": min_quantity - priced.quantity,
                "reachable": min_quantity <= obj.item.variant.product.max_order_quantity,
            }
        return {
            "applied_min_quantity": priced.tier_min_quantity,
            "saving": str(priced.bulk_saving),
            "next_tier": next_tier,
        }

    def get_line_mrp_total(self, obj) -> str | None:
        return str(obj.priced.line_mrp_total) if obj.priced else None

    def get_discount_percent(self, obj) -> str | None:
        variant, price = obj.item.variant, obj.unit_price
        if not variant.mrp or price >= variant.mrp:
            return None
        return str(((variant.mrp - price) * 100 / variant.mrp).quantize(Decimal("0.01")))

    def get_image(self, obj) -> str | None:
        images = list(obj.item.variant.product.images.all())
        if not images:
            return None
        # Prefer a picture of this exact variant, else the product's primary image.
        image = next((img for img in images if img.variant_id == obj.item.variant_id), images[0])
        request = self.context.get("request")
        return request.build_absolute_uri(image.image.url) if request else image.image.url


class CartSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="cart.id")
    items = CartLineSerializer(source="lines", many=True)
    totals = TotalsSerializer()
    offers = CartOffersSerializer()
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
