"""Orders. Line items and the delivery address are *snapshots*, so later catalog or
address edits never change a historical order. Status changes go through
`orders.services.transition_order`, which validates against `state_machine.TRANSITIONS`
and writes an OrderStatusHistory row."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    PROCESSING = "processing", "Processing"
    PACKED = "packed", "Packed"
    ASSIGNED = "assigned", "Assigned to delivery partner"
    PICKED_UP = "picked_up", "Picked up"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
    DELIVERED = "delivered", "Delivered"
    DELIVERY_FAILED = "delivery_failed", "Delivery attempt failed"  # Phase 10: back at the store
    CANCELLED = "cancelled", "Cancelled"
    RETURN_REQUESTED = "return_requested", "Return requested"
    RETURNED = "returned", "Returned"


class ShipmentStatus(models.TextChoices):
    """Where one store's part of an order is (Phase 10). The order status is derived from its
    shipments by `orders.shipments.sync_order_status`."""

    PENDING = "pending", "Waiting for a delivery partner"
    ASSIGNED = "assigned", "Delivery partner assigned"
    PICKED_UP = "picked_up", "Picked up"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Delivery attempt failed"
    CANCELLED = "cancelled", "Cancelled"


class StockState(models.TextChoices):
    """What has happened to the stock of a shipment's lines, so each movement is made once."""

    RESERVED = "reserved", "Reserved at the store"
    SOLD = "sold", "Left the store"
    RELEASED = "released", "Released (cancelled before pickup)"
    RESTOCKED = "restocked", "Back on the shelf (cancelled after a failed delivery)"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"


class PaymentMethod(models.TextChoices):
    COD = "cod", "Cash on delivery"
    ONLINE = "online", "Online (UPI / card / net banking)"


class DeliveryType(models.TextChoices):
    FAST = "fast", "Fast delivery"
    STANDARD = "standard", "Standard delivery"


class Order(TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order_number = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    store = models.ForeignKey(
        "stores.Store",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="orders",
        help_text="Fulfilment location chosen at checkout.",
    )
    address_snapshot = models.JSONField()
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )
    subtotal = models.DecimalField(**MONEY_FIELD_KWARGS, help_text="Sum of line totals (GST inclusive).")
    mrp_total = models.DecimalField(**MONEY_FIELD_KWARGS)
    discount_total = models.DecimalField(**MONEY_FIELD_KWARGS, help_text="offer_discount + coupon_discount.")
    offer_discount = models.DecimalField(**MONEY_FIELD_KWARGS, default=0, help_text="Automatic offers (Phase 6).")
    coupon_discount = models.DecimalField(**MONEY_FIELD_KWARGS, default=0)
    # Snapshot of the automatic offers applied: [{"id", "name", "badge", "discount", "skus"}].
    applied_offers = models.JSONField(default=list, blank=True)
    delivery_fee = models.DecimalField(**MONEY_FIELD_KWARGS)
    free_delivery_reason = models.CharField(
        max_length=160, blank=True, help_text="Why delivery was free (rule or offer name), when it was."
    )
    tax_total = models.DecimalField(**MONEY_FIELD_KWARGS, help_text="GST contained in the amount payable.")
    grand_total = models.DecimalField(**MONEY_FIELD_KWARGS)
    coupon = models.ForeignKey("offers.Coupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    coupon_code = models.CharField(max_length=30, blank=True)
    customer_note = models.CharField(max_length=500, blank=True)
    # Delivery promise made at placement (Phase 9; the latest of the order's shipments).
    delivery_type = models.CharField(max_length=10, choices=DeliveryType.choices, blank=True)
    estimated_ready_at = models.DateTimeField(null=True, blank=True)
    estimated_delivery_at = models.DateTimeField(null=True, blank=True)
    eta_minutes = models.PositiveIntegerField(null=True, blank=True)
    delivery_window_start = models.DateTimeField(null=True, blank=True)
    delivery_window_end = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    # Client-generated key for "Place order": a retried/double-clicked request with the same
    # key returns the first order instead of creating another. NULL (not blank) when absent,
    # because every supported database lets NULLs repeat in a unique constraint.
    idempotency_key = models.CharField(max_length=64, null=True, blank=True, editable=False)  # noqa: DJ001

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["store", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(grand_total__gte=0), name="order_grand_total_non_negative"),
            models.CheckConstraint(condition=Q(discount_total__gte=0), name="order_discount_non_negative"),
            models.UniqueConstraint(fields=["user", "idempotency_key"], name="uniq_order_idempotency_key"),
        ]

    def __str__(self) -> str:
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, on_delete=models.SET_NULL, related_name="order_items"
    )
    product = models.ForeignKey("catalog.Product", null=True, on_delete=models.SET_NULL, related_name="order_items")
    # Snapshot at purchase time
    product_name = models.CharField(max_length=200)
    variant_name = models.CharField(max_length=120, blank=True)
    sku = models.CharField(max_length=64)
    brand_name = models.CharField(max_length=120, blank=True)
    unit = models.CharField(max_length=10, blank=True)
    unit_mrp = models.DecimalField(**MONEY_FIELD_KWARGS)
    unit_price = models.DecimalField(**MONEY_FIELD_KWARGS, help_text="Price per unit charged (bulk tier applied).")
    # Phase 15 bulk pricing: the variant's normal price and the tier that set `unit_price` (null = none).
    base_unit_price = models.DecimalField(**MONEY_FIELD_KWARGS, null=True, blank=True)
    price_tier_min_quantity = models.PositiveIntegerField(null=True, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    hsn_code = models.CharField(max_length=8, blank=True)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(**MONEY_FIELD_KWARGS)
    offer_discount = models.DecimalField(
        **MONEY_FIELD_KWARGS, default=0, help_text="This line's share of automatic offers (for returns/refunds)."
    )
    # Phase 9: the shipment (store) this line is reserved at and ships from.
    shipment = models.ForeignKey(
        "OrderShipment", null=True, blank=True, on_delete=models.SET_NULL, related_name="items"
    )

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name="orderitem_quantity_positive")]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.sku}"


class OrderShipment(models.Model):
    """One store's part of an order, with the delivery estimate made when the order was placed.

    Most orders have one shipment. When no single store holds every line, the fulfilment
    engine splits the order across stores (apps/delivery/fulfillment.py); each line is reserved
    at, sold from and restocked to its shipment's store. The order status covers all shipments.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    sequence = models.PositiveSmallIntegerField(default=1)
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="shipments")
    zone = models.ForeignKey(
        "delivery.DeliveryZone", null=True, blank=True, on_delete=models.SET_NULL, related_name="shipments"
    )
    delivery_type = models.CharField(max_length=10, choices=DeliveryType.choices)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    prep_minutes = models.PositiveSmallIntegerField(default=0)
    wait_minutes = models.PositiveSmallIntegerField(default=0, help_text="Expected wait for a free rider.")
    travel_minutes = models.PositiveSmallIntegerField(default=0)
    eta_minutes = models.PositiveIntegerField(default=0)
    estimated_ready_at = models.DateTimeField(null=True, blank=True)
    estimated_delivery_at = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    eta_source = models.CharField(max_length=20, blank=True, help_text="haversine, osrm, pin or legacy.")
    created_at = models.DateTimeField(auto_now_add=True)
    # Phase 10: delivery progress of this shipment (changed only by orders.shipments / delivery.workflow).
    status = models.CharField(
        max_length=20, choices=ShipmentStatus.choices, default=ShipmentStatus.PENDING, db_index=True
    )
    stock_state = models.CharField(max_length=10, choices=StockState.choices, default=StockState.RESERVED)
    delivery_attempts = models.PositiveSmallIntegerField(default=0, help_text="Times a rider took it out.")
    picked_up_at = models.DateTimeField(null=True, blank=True)
    out_for_delivery_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=30, blank=True, help_text="Code of the last failed attempt.")
    failure_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["order_id", "sequence"]
        constraints = [models.UniqueConstraint(fields=["order", "sequence"], name="uniq_shipment_sequence")]
        indexes = [models.Index(fields=["store", "created_at"]), models.Index(fields=["store", "status"])]

    def __str__(self) -> str:
        return f"{self.order_id}/{self.sequence} from {self.store_id}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, choices=OrderStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=OrderStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["order", "created_at"])]
        verbose_name_plural = "order status history"

    def __str__(self) -> str:
        return f"{self.order_id}: {self.from_status or '∅'} → {self.to_status}"


class ReturnRequest(TimeStampedModel):
    """A customer's request to return some or all items of a delivered order (Phase 7).

    Flow (orders.returns): requested → approved → received (restocked, refund recorded)
                           requested/approved → rejected · requested → cancelled (by the customer)
    `refund_amount` is what the customer actually paid for the returned units (after offers
    and coupon), fixed when the request is made. Delivery fees are not refunded.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved — awaiting pickup/drop"
        REJECTED = "rejected", "Rejected"
        RECEIVED = "received", "Received — refund initiated"
        CANCELLED = "cancelled", "Cancelled by customer"

    class Reason(models.TextChoices):
        DAMAGED = "damaged", "Arrived damaged"
        DEFECTIVE = "defective", "Defective / not working"
        WRONG_ITEM = "wrong_item", "Wrong item delivered"
        NOT_AS_DESCRIBED = "not_as_described", "Not as described"
        NO_LONGER_NEEDED = "no_longer_needed", "No longer needed"
        OTHER = "other", "Other"

    class RefundMethod(models.TextChoices):
        ORIGINAL_PAYMENT = "original_payment", "To the original online payment"
        MANUAL = "manual", "Manual (cash on delivery orders)"

    OPEN_STATUSES = (Status.REQUESTED, Status.APPROVED)
    COUNTED_STATUSES = (Status.REQUESTED, Status.APPROVED, Status.RECEIVED)  # units no longer returnable

    return_number = models.CharField(max_length=20, unique=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="returns")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="return_requests")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.CharField(max_length=500, blank=True)
    refund_amount = models.DecimalField(**MONEY_FIELD_KWARGS)
    refund_method = models.CharField(max_length=20, choices=RefundMethod.choices)
    refund = models.OneToOneField(
        "payments.Refund", null=True, blank=True, on_delete=models.PROTECT, related_name="return_request"
    )
    decision_note = models.CharField(max_length=255, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    restocked = models.BooleanField(
        default=False, help_text="Received units went back into sellable stock (not for damaged items)."
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["order", "status"]), models.Index(fields=["status", "-created_at"])]
        constraints = [models.CheckConstraint(condition=Q(refund_amount__gte=0), name="return_refund_non_negative")]

    def __str__(self) -> str:
        return self.return_number


class ReturnItem(models.Model):
    return_request = models.ForeignKey(ReturnRequest, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(OrderItem, on_delete=models.PROTECT, related_name="return_items")
    quantity = models.PositiveIntegerField()
    refund_amount = models.DecimalField(**MONEY_FIELD_KWARGS)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="returnitem_quantity_positive"),
            models.UniqueConstraint(fields=["return_request", "order_item"], name="uniq_return_order_item"),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.order_item.sku}"
