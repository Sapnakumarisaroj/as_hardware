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


def _codes(text: str) -> set[str]:
    return {code for code in (text or "").replace(",", " ").split() if code.isdigit()}


class ServiceArea(TimeStampedModel):
    """A city the shop delivers to as a whole (e.g. Bengaluru), decided by a rule, not a PIN list.

    An address is inside when its PIN code starts with one of `postal_code_prefixes` (or is listed in
    `extra_postal_codes`) and isn't in `excluded_postal_codes`. The PIN decides when there is one;
    without a PIN, a map pin inside `polygon` or a city name in `city_names` does. Zones linked to
    the area (`DeliveryZone.service_area`) serve every address inside it; whether an order can be
    delivered, and how fast, is still the engine's call (stock, store hours, riders, ETA).

    While any area is active (and DELIVERY_RESTRICT_TO_SERVICE_AREAS is on), addresses outside every
    active area are not delivered to at all.
    """

    name = models.CharField(max_length=80, unique=True, help_text="Shown to customers, e.g. Bengaluru.")
    city_names = models.CharField(
        max_length=255, help_text="Names customers type for this city, comma separated, e.g. Bengaluru, Bangalore."
    )
    postal_code_prefixes = models.CharField(
        max_length=120, help_text="PIN codes starting with these digits are inside, e.g. 560."
    )
    extra_postal_codes = models.TextField(blank=True, help_text="Further PIN codes inside the area.")
    excluded_postal_codes = models.TextField(blank=True, help_text="PIN codes to leave out even if they match.")
    # Optional [[lat, lng], ...] ring for addresses known only by their map pin.
    polygon = models.JSONField(null=True, blank=True)
    assumed_distance_km = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("12.00"),
        validators=[MinValueValidator(Decimal("0.1"))],
        help_text="Road distance assumed when an address has no map pin or PIN centre (standard delivery only).",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def city_name_set(self) -> set[str]:
        return {_city_key(name) for name in self.city_names.split(",") if name.strip()}

    def covers_postal_code(self, postal_code: str) -> bool:
        postal_code = (postal_code or "").strip()
        if not postal_code or postal_code in _codes(self.excluded_postal_codes):
            return False
        prefixes = [p for p in self.postal_code_prefixes.replace(",", " ").split() if p.isdigit()]
        return any(postal_code.startswith(p) for p in prefixes) or postal_code in _codes(self.extra_postal_codes)

    def covers_city(self, city: str) -> bool:
        return bool(city) and _city_key(city) in self.city_name_set


def _city_key(name: str) -> str:
    """'Bengaluru Urban', 'bangalore.' -> comparable keys."""
    return " ".join("".join(ch for ch in name.lower() if ch.isalnum() or ch.isspace()).split())


class DeliveryZone(TimeStampedModel):
    """Service area of a store (Phase 9 rules, apps/delivery/fulfillment.py):

    An address is inside the zone if its PIN code is listed in `postal_codes`, or its location is
    within `radius_km` (straight line) of the store and, when a `polygon` is set, inside it, or the
    zone is linked to a city-wide `service_area` that contains the address.
    Fee: `delivery_fee_override` / `free_delivery_min_order` replace the global defaults.
    Fast delivery: only if enabled here and the calculated ETA ≤ `fast_delivery_max_minutes`
    (or FAST_DELIVERY_MAX_MINUTES).
    """

    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE, related_name="delivery_zones")
    name = models.CharField(max_length=120)
    service_area = models.ForeignKey(
        ServiceArea,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="zones",
        help_text="Serve every address in this city (radius and PIN list still apply as well).",
    )
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
    cod_enabled = models.BooleanField(default=True, help_text="Allow cash on delivery for addresses in this zone.")
    unloading_available = models.BooleanField(
        default=False, help_text="Offer the paid unloading service (ground level) for addresses in this zone."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["store_id", "name"]
        indexes = [models.Index(fields=["store", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.radius_km} km)"

    @property
    def postal_code_set(self) -> set[str]:
        return _codes(self.postal_codes)


def default_distance_bands() -> list[dict]:
    """Shop policy (approved): ₹40 up to 5 km, ₹80 beyond (Bengaluru only; free from FREE_DELIVERY_MIN_ORDER)."""
    return [
        {"up_to_km": "5", "fee": "40"},
        {"up_to_km": "60", "fee": "80"},
    ]


class DeliveryCharges(models.Model):
    """Shop-wide delivery charge rules, editable by administrators (one row, pk=1).

    Fee by road distance from the store: the first band whose `up_to_km` is not exceeded. Beyond the
    last band, `extra_per_km` is added for every started km above it (blank = the last band's fee).
    A zone's `delivery_fee_override` still wins. Distance comes from the routing provider (OSRM =
    road distance) or is an estimate (straight line × ROAD_DISTANCE_FACTOR, or the city's assumed
    distance when coordinates are missing); estimates are labelled as such to customers.
    """

    distance_bands = models.JSONField(
        default=default_distance_bands,
        blank=True,
        help_text='[{"up_to_km": "3", "fee": "30"}, …] in increasing km. Empty = the flat DELIVERY_FEE setting.',
    )
    extra_per_km = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Added per started km beyond the last band. Blank = the last band's fee applies.",
    )
    free_first_orders = models.PositiveSmallIntegerField(
        default=0,  # promotion off by shop policy; an administrator may switch it on deliberately
        help_text="Free delivery on each customer's first N orders that would carry a delivery charge (0 = off).",
    )
    unloading_fee = models.DecimalField(
        **MONEY_FIELD_KWARGS,
        default=Decimal("199.00"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Optional unloading service (ground level only), offered in zones that allow it.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = verbose_name_plural = "delivery charges"

    def __str__(self) -> str:
        return "Delivery charges"

    @classmethod
    def load(cls) -> "DeliveryCharges":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        from django.core.exceptions import ValidationError

        try:
            bands = parse_bands(self.distance_bands)
        except ValueError as exc:
            raise ValidationError({"distance_bands": str(exc)}) from exc
        self.distance_bands = [{"up_to_km": str(km), "fee": str(fee)} for km, fee in bands]

    def bands(self) -> list[tuple[Decimal, Decimal]]:
        return parse_bands(self.distance_bands)


def parse_bands(raw) -> list[tuple[Decimal, Decimal]]:
    """[(up_to_km, fee)] sorted, validated: km strictly increasing and > 0, fees ≥ 0."""
    from decimal import InvalidOperation

    if not isinstance(raw, list):
        raise ValueError("Distance bands must be a list.")
    bands = []
    for row in raw:
        try:
            km, fee = Decimal(str(row["up_to_km"])), Decimal(str(row["fee"]))
        except (KeyError, TypeError, InvalidOperation):
            raise ValueError('Each band needs "up_to_km" and "fee" numbers.') from None
        if km <= 0 or fee < 0:
            raise ValueError("Band distances must be above 0 and fees 0 or more.")
        bands.append((km, fee.quantize(Decimal("0.01"))))
    bands.sort()
    if len({km for km, _ in bands}) != len(bands):
        raise ValueError("Two bands have the same distance.")
    return bands


class CoverageReview(TimeStampedModel):
    """A customer address the delivery area doesn't cover, flagged for an administrator to look at
    (e.g. add its PIN code to a zone or the city). One open review per address."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COVERED = "covered", "Now covered"
        DECLINED = "declined", "Not served"

    address = models.ForeignKey("accounts.Address", on_delete=models.CASCADE, related_name="coverage_reviews")
    postal_code = models.CharField(max_length=6, blank=True)
    city = models.CharField(max_length=80, blank=True)
    message = models.CharField(max_length=255, blank=True, help_text="What the customer was told.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["address"], condition=Q(status="open"), name="one_open_coverage_review_per_address"
            )
        ]

    def __str__(self) -> str:
        return f"{self.postal_code or self.city or 'address'} ({self.get_status_display()})"


class FreeDeliveryRule(TimeStampedModel):
    """Free delivery when the qualifying part of an order reaches `threshold` (Phase 15).

    Works next to the zone's own `free_delivery_min_order` (which stays the basic rule). A rule
    applies only while live (`is_active`, start ≤ now < end) and, if `zones` are chosen, only for
    orders delivered from one of those zones. With `products`/`categories` chosen, only those
    lines count towards the threshold (a category covers everything below it); none = the whole
    order. Amounts are after offers and coupon. Calculated in `orders.pricing` only.
    """

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    threshold = models.DecimalField(**MONEY_FIELD_KWARGS, validators=[MinValueValidator(0)])
    zones = models.ManyToManyField(DeliveryZone, blank=True, related_name="free_delivery_rules")
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="free_delivery_rules")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="free_delivery_rules")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["threshold", "id"]
        indexes = [models.Index(fields=["is_active", "starts_at", "ends_at"])]
        constraints = [models.CheckConstraint(condition=Q(threshold__gte=0), name="free_delivery_threshold_gte_0")]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End must be after start."})


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
