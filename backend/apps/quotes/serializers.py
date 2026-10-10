from rest_framework import serializers

from apps.core.money import q

from .models import Quote, QuoteItem


class QuoteItemSerializer(serializers.ModelSerializer):
    variant_id = serializers.IntegerField(source="variant.id", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    product_name = serializers.CharField(source="variant.product.name", read_only=True)
    product_slug = serializers.CharField(source="variant.product.slug", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    unit = serializers.CharField(source="variant.product.unit", read_only=True)
    unit_mrp = serializers.DecimalField(source="variant.mrp", max_digits=12, decimal_places=2, read_only=True)
    quoted_line_total = serializers.SerializerMethodField()
    list_line_total = serializers.SerializerMethodField()

    class Meta:
        model = QuoteItem
        fields = [
            "id",
            "variant_id",
            "sku",
            "product_name",
            "product_slug",
            "variant_name",
            "unit",
            "quantity",
            "customer_note",
            "unit_mrp",
            "list_unit_price",
            "list_line_total",
            "quoted_unit_price",
            "quoted_line_total",
        ]
        read_only_fields = fields

    def get_quoted_line_total(self, obj) -> str | None:
        return str(q(obj.quoted_unit_price * obj.quantity)) if obj.quoted_unit_price is not None else None

    def get_list_line_total(self, obj) -> str:
        return str(q(obj.list_unit_price * obj.quantity))


class QuoteSerializer(serializers.ModelSerializer):
    """Totals here are line sums for reading the quotation; checkout re-prices through the order engine
    (delivery fee, credits and stock are decided there)."""

    items = QuoteItemSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    quoted_goods_total = serializers.SerializerMethodField()
    list_goods_total = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.order_number", default=None, read_only=True)
    can_accept = serializers.SerializerMethodField()
    can_checkout = serializers.SerializerMethodField()
    can_close = serializers.SerializerMethodField()

    class Meta:
        model = Quote
        fields = [
            "id",
            "number",
            "status",
            "status_label",
            "customer_note",
            "address",
            "buyer_type",
            "business_name",
            "gstin",
            "shop_note",
            "valid_until",
            "quoted_at",
            "accepted_at",
            "closed_reason",
            "order_number",
            "items",
            "list_goods_total",
            "quoted_goods_total",
            "can_accept",
            "can_checkout",
            "can_close",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_quoted_goods_total(self, obj) -> str | None:
        items = list(obj.items.all())
        if not items or any(i.quoted_unit_price is None for i in items):
            return None
        return str(q(sum(i.quoted_unit_price * i.quantity for i in items)))

    def get_list_goods_total(self, obj) -> str:
        return str(q(sum((i.list_unit_price * i.quantity for i in obj.items.all()), q(0))))

    def get_can_accept(self, obj) -> bool:
        return obj.status == Quote.Status.QUOTED and not obj.is_expired

    def get_can_checkout(self, obj) -> bool:
        return obj.status == Quote.Status.ACCEPTED and not obj.is_expired

    def get_can_close(self, obj) -> bool:
        return obj.status in (Quote.Status.REQUESTED, Quote.Status.QUOTED, Quote.Status.ACCEPTED)


class AdminQuoteSerializer(QuoteSerializer):
    customer_name = serializers.CharField(source="user.get_full_name", read_only=True)
    customer_email = serializers.EmailField(source="user.email", read_only=True)
    customer_phone = serializers.CharField(source="user.phone", default="", read_only=True)

    class Meta(QuoteSerializer.Meta):
        fields = [*QuoteSerializer.Meta.fields, "customer_name", "customer_email", "customer_phone"]
        read_only_fields = fields


class RequestLineSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RequestQuoteSerializer(serializers.Serializer):
    items = RequestLineSerializer(many=True, required=False)
    from_cart = serializers.BooleanField(required=False, default=False, help_text="Use the cart's lines.")
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    address_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("items") and not attrs["from_cart"]:
            raise serializers.ValidationError({"items": ["Add at least one product, or request from your cart."]})
        return attrs


class CloseQuoteSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class QuotationLineSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)


class SendQuotationSerializer(serializers.Serializer):
    lines = QuotationLineSerializer(many=True)
    valid_days = serializers.IntegerField(min_value=1, max_value=90, default=7)
    shop_note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class RejectQuoteSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
