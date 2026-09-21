"""Payments and refunds.

Security: no card numbers, CVV, UPI PINs or bank credentials are ever stored — the
gateway handles those. We keep only gateway reference IDs, amounts, statuses and a
*sanitised* metadata blob.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS


class Payment(TimeStampedModel):
    class Provider(models.TextChoices):
        MOCK = "mock", "Mock (development)"
        RAZORPAY = "razorpay", "Razorpay"
        COD = "cod", "Cash on delivery"

    class Method(models.TextChoices):
        COD = "cod", "Cash on delivery"
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        NETBANKING = "netbanking", "Net banking"
        WALLET = "wallet", "Wallet"
        UNKNOWN = "unknown", "Not yet known"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Pending"
        AUTHORIZED = "authorized", "Authorized"
        CAPTURED = "captured", "Captured"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.UNKNOWN)
    amount = models.DecimalField(**MONEY_FIELD_KWARGS)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True)
    provider_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    provider_payment_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True, help_text="Sanitised gateway data only. Never card data.")
    captured_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["order", "status"])]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive")]

    def __str__(self) -> str:
        return f"{self.provider}:{self.public_id} {self.amount} {self.status}"


class Refund(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(**MONEY_FIELD_KWARGS)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    reason = models.CharField(max_length=255)
    provider_refund_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive")]

    def __str__(self) -> str:
        return f"Refund {self.amount} for {self.payment_id} ({self.status})"
