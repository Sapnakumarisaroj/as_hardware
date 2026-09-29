"""Delivery: zones, PIN codes, partners, assignments and their status history.

Phase 9: the fulfilment/ETA engine (fulfillment.py, eta.py, locations.py) and who may carry a
shipment (assignment.py). Phase 10: the rider workflow (workflow.py, otp.py, proof.py, cod.py).
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.core.money import MONEY_FIELD_KWARGS
from apps.core.storage import private_storage
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
    """One rider's job: deliver a shipment, or collect an approved return (Phase 10).

    Delivery:       assigned → accepted → picked_up → out_for_delivery → delivered
    Return pickup:  assigned → accepted → picked_up (from the customer) → delivered (to the store)
    Either:         assigned/accepted → rejected (by the rider) or cancelled (by staff / order cancelled)
                    picked_up/out_for_delivery → failed
    Every change goes through apps.delivery.workflow, which locks, validates and writes history.
    """

    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        ACCEPTED = "accepted", "Accepted"
        PICKED_UP = "picked_up", "Picked up"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Delivery failed"
        REJECTED = "rejected", "Rejected by the delivery partner"
        CANCELLED = "cancelled", "Cancelled / reassigned"

    class Kind(models.TextChoices):
        DELIVERY = "delivery", "Delivery to the customer"
        RETURN_PICKUP = "return_pickup", "Return pickup from the customer"

    class FailureCode(models.TextChoices):
        CUSTOMER_UNAVAILABLE = "customer_unavailable", "Customer not available"
        WRONG_ADDRESS = "wrong_address", "Address wrong or not found"
        CUSTOMER_REFUSED = "customer_refused", "Customer refused the delivery"
        PAYMENT_NOT_READY = "payment_not_ready", "Customer could not pay"
        DAMAGED = "damaged", "Goods damaged on the way"
        VEHICLE_PROBLEM = "vehicle_problem", "Vehicle breakdown or accident"
        OTHER = "other", "Other"

    class CodMethod(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI to the store"

    ACTIVE_STATUSES = (Status.ASSIGNED, Status.ACCEPTED, Status.PICKED_UP, Status.OUT_FOR_DELIVERY)
    BEFORE_PICKUP = (Status.ASSIGNED, Status.ACCEPTED)
    WITH_GOODS = (Status.PICKED_UP, Status.OUT_FOR_DELIVERY)

    kind = models.CharField(max_length=15, choices=Kind.choices, default=Kind.DELIVERY)
    return_request = models.ForeignKey(
        "orders.ReturnRequest", null=True, blank=True, on_delete=models.PROTECT, related_name="pickups"
    )
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
    rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=255, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=30, choices=FailureCode.choices, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    # Delivery OTP (apps/delivery/otp.py). The code itself is never stored: `otp_hash` is a keyed
    # hash of it, and the customer's copy is re-derived from `otp_nonce` with the server secret.
    otp_hash = models.CharField(max_length=128, blank=True)
    otp_nonce = models.CharField(max_length=32, blank=True)
    otp_issued_at = models.DateTimeField(null=True, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0, help_text="Wrong codes entered for the current OTP.")
    otp_verified_at = models.DateTimeField(null=True, blank=True)
    # Proof of delivery: private storage, served only through authenticated API views.
    proof_image = models.ImageField(
        upload_to=delivery_proof_path,
        storage=private_storage,
        blank=True,
        validators=[FileExtensionValidator(ALLOWED_IMAGE_EXTENSIONS), MaxFileSizeValidator(5)],
    )
    proof_uploaded_at = models.DateTimeField(null=True, blank=True)
    received_by = models.CharField(max_length=120, blank=True, help_text="Who took the delivery at the door.")
    completed_without_otp = models.BooleanField(default=False, help_text="Closed by store staff (audit-logged).")
    delivery_notes = models.CharField(max_length=500, blank=True)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    earning_amount = models.DecimalField(**MONEY_FIELD_KWARGS, default=Decimal("0.00"))
    # Cash on delivery: what this rider must collect for this shipment, and what happened to it.
    cod_amount_due = models.DecimalField(**MONEY_FIELD_KWARGS, default=Decimal("0.00"))
    cod_collected_amount = models.DecimalField(**MONEY_FIELD_KWARGS, null=True, blank=True)
    cod_method = models.CharField(max_length=10, choices=CodMethod.choices, blank=True)
    cod_reference = models.CharField(max_length=60, blank=True, help_text="UPI reference, if paid by UPI.")
    cod_collected_at = models.DateTimeField(null=True, blank=True)
    cod_handed_over_at = models.DateTimeField(null=True, blank=True, help_text="Cash received by the store.")
    cod_handed_over_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cod_handover_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(fields=["partner", "status"]),
            models.Index(fields=["order", "status"]),
            models.Index(fields=["partner", "cod_handed_over_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(earning_amount__gte=0), name="assignment_earning_non_negative"),
            models.CheckConstraint(condition=Q(cod_amount_due__gte=0), name="assignment_cod_due_non_negative"),
        ]

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def cash_in_hand(self) -> Decimal:
        """Cash this rider still has to hand over to the store for this delivery."""
        if self.cod_method == self.CodMethod.CASH and self.cod_collected_at and not self.cod_handed_over_at:
            return self.cod_collected_amount or Decimal("0.00")
        return Decimal("0.00")

    def __str__(self) -> str:
        return f"{self.order_id} → {self.partner_id} ({self.status})"


class DeliveryStatusHistory(models.Model):
    assignment = models.ForeignKey(DeliveryAssignment, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=DeliveryAssignment.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "delivery status history"

    def __str__(self) -> str:
        return f"{self.assignment_id}: {self.from_status or '∅'} → {self.to_status}"
