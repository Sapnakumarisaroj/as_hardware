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
    CANCELLED = "cancelled", "Cancelled"
    RETURN_REQUESTED = "return_requested", "Return requested"
    RETURNED = "returned", "Returned"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"


class PaymentMethod(models.TextChoices):
    COD = "cod", "Cash on delivery"
    ONLINE = "online", "Online (UPI / card / net banking)"


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
    discount_total = models.DecimalField(**MONEY_FIELD_KWARGS)
    delivery_fee = models.DecimalField(**MONEY_FIELD_KWARGS)
    tax_total = models.DecimalField(**MONEY_FIELD_KWARGS, help_text="GST contained in the amount payable.")
    grand_total = models.DecimalField(**MONEY_FIELD_KWARGS)
    coupon = models.ForeignKey("offers.Coupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    coupon_code = models.CharField(max_length=30, blank=True)
    customer_note = models.CharField(max_length=500, blank=True)
    estimated_delivery_at = models.DateTimeField(null=True, blank=True)
    eta_minutes = models.PositiveIntegerField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

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
    unit_price = models.DecimalField(**MONEY_FIELD_KWARGS)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    hsn_code = models.CharField(max_length=8, blank=True)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(**MONEY_FIELD_KWARGS)

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name="orderitem_quantity_positive")]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.sku}"


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
