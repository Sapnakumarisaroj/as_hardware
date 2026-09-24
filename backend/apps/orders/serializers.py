from django.utils import timezone
from rest_framework import serializers

from apps.payments.models import Payment, Refund

from .checkout import ETA_PENDING_MESSAGE
from .models import Order, OrderItem, OrderStatus, OrderStatusHistory, PaymentMethod, PaymentStatus
from .state_machine import CUSTOMER_CANCELLABLE

IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_\-]{8,64}$"  # e.g. a browser crypto.randomUUID()


def _image_url(product, request) -> str | None:
    """Primary image of a product (prefetched `images`), or None if the product is gone."""
    if product is None:
        return None
    images = list(product.images.all())
    if not images:
        return None
    url = images[0].image.url
    return request.build_absolute_uri(url) if request else url


class OrderItemSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    product_slug = serializers.CharField(source="product.slug", read_only=True, default=None)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_slug",
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
            "offer_discount",
            "image",
        ]

    def get_image(self, obj) -> str | None:
        return _image_url(obj.product, self.context.get("request"))


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


class PaymentSummarySerializer(serializers.ModelSerializer):
    client_payload = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "public_id",
            "provider",
            "method",
            "amount",
            "currency",
            "status",
            "failure_reason",
            "captured_at",
            "created_at",
            "client_payload",
        ]

    def get_client_payload(self, obj) -> dict:
        # Only public, non-secret data needed to open the payment widget.
        if obj.status != Payment.Status.CREATED:
            return {}
        return obj.metadata.get("client_payload", {})


class RefundSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ["public_id", "amount", "status", "reason", "created_at", "processed_at"]


class OrderListSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()
    item_names = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    delivery_message = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "order_number",
            "status",
            "payment_method",
            "payment_status",
            "grand_total",
            "item_count",
            "item_names",
            "image",
            "estimated_delivery_at",
            "delivery_message",
            "created_at",
        ]

    def get_item_count(self, obj) -> int:
        return sum(item.quantity for item in obj.items.all())

    def get_item_names(self, obj) -> list[str]:
        return [item.product_name for item in list(obj.items.all())[:3]]

    def get_image(self, obj) -> str | None:
        items = list(obj.items.all())
        return _image_url(items[0].product, self.context.get("request")) if items else None

    def get_delivery_message(self, obj) -> str:
        return delivery_message(obj)


def delivery_message(order: Order) -> str:
    """Honest, status-based delivery text. A real ETA appears only once the backend sets one."""
    if order.status == OrderStatus.DELIVERED:
        return "Delivered"
    if order.status in (OrderStatus.CANCELLED, OrderStatus.RETURNED, OrderStatus.RETURN_REQUESTED):
        return ""
    if order.status == OrderStatus.PENDING and order.payment_method == PaymentMethod.ONLINE:
        return "Complete the payment to confirm your order."
    if order.estimated_delivery_at:
        return f"Estimated delivery by {timezone.localtime(order.estimated_delivery_at):%d %b, %I:%M %p}"
    if order.status == OrderStatus.OUT_FOR_DELIVERY:
        return "Out for delivery — arriving soon."
    return ETA_PENDING_MESSAGE


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    payments = PaymentSummarySerializer(many=True, read_only=True)
    refunds = serializers.SerializerMethodField()
    store_name = serializers.CharField(source="store.name", read_only=True, default=None)
    can_cancel = serializers.SerializerMethodField()
    can_retry_payment = serializers.SerializerMethodField()
    delivery_message = serializers.SerializerMethodField()

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
            "offer_discount",
            "coupon_discount",
            "applied_offers",
            "delivery_fee",
            "tax_total",
            "grand_total",
            "coupon_code",
            "customer_note",
            "estimated_delivery_at",
            "eta_minutes",
            "delivery_message",
            "cancellation_reason",
            "cancelled_at",
            "delivered_at",
            "created_at",
            "can_cancel",
            "can_retry_payment",
            "items",
            "status_history",
            "payments",
            "refunds",
        ]

    def get_refunds(self, obj) -> list[dict]:
        refunds = [refund for payment in obj.payments.all() for refund in payment.refunds.all()]
        return RefundSummarySerializer(refunds, many=True).data

    def get_can_cancel(self, obj) -> bool:
        return obj.status in CUSTOMER_CANCELLABLE

    def get_can_retry_payment(self, obj) -> bool:
        return (
            obj.payment_method == PaymentMethod.ONLINE
            and obj.status == OrderStatus.PENDING
            and obj.payment_status != PaymentStatus.PAID
            and not any(p.status == Payment.Status.CREATED for p in obj.payments.all())
        )

    def get_delivery_message(self, obj) -> str:
        return delivery_message(obj)


class PlaceOrderSerializer(serializers.Serializer):
    """Only identifiers and choices are accepted — never prices or totals.

    `expected_total` is the grand total the customer saw; it is *compared* with the server's
    own calculation (mismatch → 409 totals_changed), never used as the price.
    """

    address_id = serializers.IntegerField(min_value=1)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    coupon_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    customer_note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    expected_total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    idempotency_key = serializers.RegexField(IDEMPOTENCY_KEY_PATTERN, required=False, allow_null=True, allow_blank=True)


class CheckoutPreviewRequestSerializer(serializers.Serializer):
    address_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    coupon_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")


class _IssueSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class _CouponResultSerializer(serializers.Serializer):
    code = serializers.CharField()
    description = serializers.CharField()
    discount = serializers.DecimalField(max_digits=12, decimal_places=2)


class _CouponErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField()


class DeliveryQuoteSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    fee = serializers.DecimalField(max_digits=12, decimal_places=2)
    free_delivery_min_order = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_to_free_delivery = serializers.DecimalField(max_digits=12, decimal_places=2)
    fast_delivery_possible = serializers.BooleanField()
    eta_minutes = serializers.IntegerField(allow_null=True)
    message = serializers.CharField()


class CheckoutPreviewSerializer(serializers.Serializer):
    """Server-calculated checkout state. The frontend displays it; it never recomputes money."""

    cart = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()
    address_id = serializers.IntegerField(source="address.id", allow_null=True, default=None)
    coupon = serializers.SerializerMethodField()
    coupon_error = _CouponErrorSerializer(allow_null=True)
    delivery = DeliveryQuoteSerializer()
    offers = serializers.SerializerMethodField()
    blocking_issues = _IssueSerializer(many=True)
    can_place_order = serializers.BooleanField()
    payment_methods = serializers.SerializerMethodField()

    def get_cart(self, obj) -> dict:
        from apps.carts.serializers import CartSerializer

        return CartSerializer(obj.cart, context=self.context).data

    def get_totals(self, obj) -> dict:
        from apps.carts.serializers import TotalsSerializer

        return TotalsSerializer(obj.totals).data

    def get_offers(self, obj) -> dict:
        from apps.carts.serializers import CartOffersSerializer

        return CartOffersSerializer(obj.offers).data

    def get_coupon(self, obj) -> dict | None:
        if obj.coupon is None:
            return None
        return _CouponResultSerializer(
            {"code": obj.coupon.code, "description": obj.coupon.description, "discount": obj.coupon_discount}
        ).data

    def get_payment_methods(self, obj) -> list[dict]:
        from integrations.payments import get_payment_provider

        provider = get_payment_provider()
        online_label = "Mock online payment (development — no real money)" if provider.is_test_mode else "Pay online"
        return [
            {"value": PaymentMethod.ONLINE, "label": online_label, "test_mode": provider.is_test_mode},
            {"value": PaymentMethod.COD, "label": "Cash on delivery", "test_mode": False},
        ]


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class TransitionOrderSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
