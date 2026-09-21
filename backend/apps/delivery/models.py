"""Delivery foundation: zones, partners, assignments and their status history.

The assignment/ETA algorithms arrive in Phases 9–10. "One active assignment per order"
is enforced by the delivery service then (no partial unique indexes on MySQL).
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS
from apps.core.uploads import ALLOWED_IMAGE_EXTENSIONS, delivery_proof_path
from apps.core.validators import MaxFileSizeValidator, phone_validator

LAT_VALIDATORS = [MinValueValidator(-90), MaxValueValidator(90)]
LNG_VALIDATORS = [MinValueValidator(-180), MaxValueValidator(180)]


class DeliveryZone(TimeStampedModel):
    """Service area around a store: a radius, optionally refined by a polygon."""

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="delivery_zones")
    name = models.CharField(max_length=120)
    radius_km = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("5.00"), validators=[MinValueValidator(Decimal("0.1"))]
    )
    # Optional [[lat, lng], ...] ring, checked in Python (portable; no GIS extension needed).
    polygon = models.JSONField(null=True, blank=True)
    fast_delivery_enabled = models.BooleanField(default=True)
    delivery_fee_override = models.DecimalField(**MONEY_FIELD_KWARGS, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["store_id", "name"]
        indexes = [models.Index(fields=["store", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.radius_km} km)"


class DeliveryPartner(TimeStampedModel):
    class Status(models.TextChoices):
        OFFLINE = "offline", "Offline"
        AVAILABLE = "available", "Available"
        BUSY = "busy", "On a delivery"

    class Vehicle(models.TextChoices):
        BICYCLE = "bicycle", "Bicycle"
        SCOOTER = "scooter", "Scooter / bike"
        CAR = "car", "Car"
        VAN = "van", "Van / tempo"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delivery_partner")
    phone = models.CharField(max_length=15, validators=[phone_validator])
    vehicle_type = models.CharField(max_length=10, choices=Vehicle.choices, default=Vehicle.SCOOTER)
    vehicle_number = models.CharField(max_length=20, blank=True)
    home_store = models.ForeignKey(
        "stores.Store", null=True, blank=True, on_delete=models.SET_NULL, related_name="delivery_partners"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OFFLINE, db_index=True)
    is_verified = models.BooleanField(default=False, help_text="Documents checked by an admin.")
    is_active = models.BooleanField(default=True)
    current_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, validators=LAT_VALIDATORS
    )
    current_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, validators=LNG_VALIDATORS
    )
    last_location_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["home_store", "status", "is_active"])]

    def __str__(self) -> str:
        return f"{self.user.get_full_name()} ({self.get_status_display()})"


class DeliveryAssignment(TimeStampedModel):
    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        ACCEPTED = "accepted", "Accepted"
        PICKED_UP = "picked_up", "Picked up"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Delivery failed"
        CANCELLED = "cancelled", "Cancelled / reassigned"

    ACTIVE_STATUSES = (Status.ASSIGNED, Status.ACCEPTED, Status.PICKED_UP, Status.OUT_FOR_DELIVERY)

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="delivery_assignments")
    partner = models.ForeignKey(DeliveryPartner, on_delete=models.PROTECT, related_name="assignments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED, db_index=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    out_for_delivery_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    # Only a hash of the customer's delivery OTP is stored.
    otp_hash = models.CharField(max_length=128, blank=True)
    otp_verified_at = models.DateTimeField(null=True, blank=True)
    proof_image = models.ImageField(
        upload_to=delivery_proof_path,
        blank=True,
        validators=[FileExtensionValidator(ALLOWED_IMAGE_EXTENSIONS), MaxFileSizeValidator(5)],
    )
    delivery_notes = models.CharField(max_length=500, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    earning_amount = models.DecimalField(**MONEY_FIELD_KWARGS, default=Decimal("0.00"))

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(fields=["partner", "status"]),
            models.Index(fields=["order", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(earning_amount__gte=0), name="assignment_earning_non_negative")
        ]

    def __str__(self) -> str:
        return f"{self.order_id} → {self.partner_id} ({self.status})"


class DeliveryStatusHistory(models.Model):
    assignment = models.ForeignKey(DeliveryAssignment, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=DeliveryAssignment.Status.choices)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "delivery status history"

    def __str__(self) -> str:
        return f"{self.assignment_id}: {self.from_status or '∅'} → {self.to_status}"
