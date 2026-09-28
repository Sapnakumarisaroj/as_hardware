"""Delivery: zones, PIN codes, partners, assignments and their status history.

Phase 9 adds the fulfilment/ETA engine (fulfillment.py, eta.py, locations.py) and the assignment
foundation (assignment.py). The rider workflow (accept, pickup, OTP, proof) is Phase 10.
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
    """Service area of a store (Phase 9 rules, apps/delivery/fulfillment.py):

    An address is inside the zone if its PIN code is listed in `postal_codes`, or its location is
    within `radius_km` (straight line) of the store and, when a `polygon` is set, inside it.
    Fee: `delivery_fee_override` / `free_delivery_min_order` replace the global defaults.
    Fast delivery: only if enabled here and the calculated ETA ≤ `fast_delivery_max_minutes`
    (or FAST_DELIVERY_MAX_MINUTES).
    """

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="delivery_zones")
    name = models.CharField(max_length=120)
    radius_km = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("5.00"), validators=[MinValueValidator(Decimal("0.1"))]
    )
    # Optional [[lat, lng], ...] ring, checked in Python (portable; no GIS extension needed).
    polygon = models.JSONField(null=True, blank=True)
    postal_codes = models.TextField(
        blank=True, help_text="PIN codes always served by this zone (comma or space separated), e.g. 411038, 411029."
    )
    fast_delivery_enabled = models.BooleanField(default=True)
    fast_delivery_max_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Offer fast delivery only when the ETA is at most this. Blank = global setting.",
    )
    delivery_fee_override = models.DecimalField(
        **MONEY_FIELD_KWARGS, null=True, blank=True, help_text="Delivery fee in this zone. Blank = global setting."
    )
    free_delivery_min_order = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        null=True,
        blank=True,
        help_text="Order value (after discounts) for free delivery in this zone. Blank = global setting.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["store_id", "name"]
        indexes = [models.Index(fields=["store", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.radius_km} km)"

    @property
    def postal_code_set(self) -> set[str]:
        return {code for code in self.postal_codes.replace(",", " ").split() if code.isdigit()}


class PinCode(models.Model):
    """Known PIN codes with an approximate centre point (admin-managed, or learned from geocoding).

    Lets the engine estimate distance for a PIN typed in the location selector, or for an address
    saved without a map pin. Not a serviceability list by itself: zones decide that.
    """

    postal_code = models.CharField(max_length=6, unique=True)
    area = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, validators=LAT_VALIDATORS)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, validators=LNG_VALIDATORS)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["postal_code"]
        verbose_name = "PIN code"

    def __str__(self) -> str:
        return f"{self.postal_code} {self.area}".strip()


class GeocodeCache(models.Model):
    """Every geocoding answer (including "not found"), so each query hits OpenStreetMap at most once."""

    query = models.CharField(max_length=255, unique=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.query


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
    max_active_assignments = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)], help_text="Deliveries this partner may carry at once."
    )
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
    # Phase 9: the shipment (one store's part of the order) this rider carries. One active
    # assignment per shipment is enforced by apps.delivery.assignment (locks, no partial index).
    shipment = models.ForeignKey(
        "orders.OrderShipment", null=True, blank=True, on_delete=models.PROTECT, related_name="assignments"
    )
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
