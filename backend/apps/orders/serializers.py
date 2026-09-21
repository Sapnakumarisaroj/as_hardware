from rest_framework import serializers

from apps.payments.models import Payment

from .models import Order, OrderItem, OrderStatus, OrderStatusHistory, PaymentMethod


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "variant",
            "product_name",
            "variant_name",
            "sku",
            "brand_name",
            "unit",
            "unit_mrp",
            "unit_price",
            "gst_rate",
            "quantity",
            "line_total",
        ]


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


class PaymentSummarySerializer(serializers.ModelSerializer):
    client_payload = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["public_id", "provider", "method", "amount", "currency", "status", "client_payload"]

    def get_client_payload(self, obj) -> dict:
        # Only public, non-secret data needed to open the payment widget.
        if obj.status != Payment.Status.CREATED:
            return {}
        return obj.metadata.get("client_payload", {})


class OrderListSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Order
        fields = [
            "order_number",
            "status",
            "payment_method",
            "payment_status",
            "grand_total",
            "item_count",
            "estimated_delivery_at",
            "created_at",
        ]


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    payments = PaymentSummarySerializer(many=True, read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True, default=None)

    class Meta:
        model = Order
        fields = [
            "order_number",
            "public_id",
            "status",
            "payment_method",
            "payment_status",
            "address_snapshot",
            "store_name",
            "subtotal",
            "mrp_total",
            "discount_total",
            "delivery_fee",
            "tax_total",
            "grand_total",
            "coupon_code",
            "customer_note",
            "estimated_delivery_at",
            "eta_minutes",
            "cancellation_reason",
            "cancelled_at",
            "delivered_at",
            "created_at",
            "items",
            "status_history",
            "payments",
        ]


class PlaceOrderSerializer(serializers.Serializer):
    """Only identifiers and choices are accepted — never prices or totals."""

    address_id = serializers.IntegerField(min_value=1)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    coupon_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    customer_note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class TransitionOrderSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
