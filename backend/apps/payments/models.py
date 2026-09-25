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
    # Phase 8: gateway submission. The reference is sent with the refund so a retried call after a
    # timeout finds the first attempt instead of refunding twice; a manual retry of a *failed*
    # refund gets a new reference (the gateway would otherwise return the failed one).
    provider_reference = models.CharField(max_length=64, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    # Manual refunds (cash-on-delivery money, or paid outside the gateway): who and how.
    manual_reference = models.CharField(max_length=100, blank=True, help_text="UPI/bank reference or cash receipt.")
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive")]

    def __str__(self) -> str:
        return f"Refund {self.amount} for {self.payment_id} ({self.status})"

    @property
    def is_manual(self) -> bool:
        """Cash-on-delivery money can't go back through a gateway; staff refund it and record it."""
        return self.payment.provider == Payment.Provider.COD


class WebhookEvent(models.Model):
    """Every signature-verified gateway webhook, once (unique per provider + event id).

    A redelivered event finds its row and is not processed again. Only a sanitised payload is kept
    (ids, amounts, statuses, error text): never card, VPA, bank, email or phone details.
    """

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored (not relevant)"
        FAILED = "failed", "Failed (will be retried by the gateway)"

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    note = models.CharField(max_length=255, blank=True)
    deliveries = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_event")]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type} {self.event_id}"
