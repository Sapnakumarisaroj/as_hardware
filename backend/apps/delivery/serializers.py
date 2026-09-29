from urllib.parse import quote_plus

from django.conf import settings
from rest_framework import serializers

from . import otp
from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory, DeliveryZone

A = DeliveryAssignment.Status
KIND = DeliveryAssignment.Kind


class DeliveryPartnerSerializer(serializers.ModelSerializer):
    """The rider's own profile. Only `status` (online/offline) can be changed, through PATCH."""

    full_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    home_store_name = serializers.CharField(source="home_store.name", read_only=True, default=None)
    active_assignments = serializers.SerializerMethodField()
    cash_in_hand = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryPartner
        fields = [
            "full_name",
            "email",
            "phone",
            "vehicle_type",
            "vehicle_number",
            "home_store_name",
            "status",
            "is_verified",
            "is_active",
            "max_active_assignments",
            "active_assignments",
            "cash_in_hand",
            "last_location_at",
        ]
        read_only_fields = [f for f in fields if f != "status"]

    def get_active_assignments(self, obj) -> int:
        return obj.assignments.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).count()

    def get_cash_in_hand(self, obj) -> str:
        from .cod import cash_in_hand

        return str(cash_in_hand(obj))


class AvailabilitySerializer(serializers.Serializer):
    # "busy" is set by the system when an assignment is active, never by the partner.
    status = serializers.ChoiceField(choices=[DeliveryPartner.Status.OFFLINE, DeliveryPartner.Status.AVAILABLE])


class LocationPingSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)


class DeliveryStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


def map_links(latitude, longitude, address: str) -> dict:
    """Free navigation links: OpenStreetMap in the browser, `geo:` for the phone's own maps app."""
    if latitude is not None and longitude is not None:
        lat, lng = f"{float(latitude):.6f}", f"{float(longitude):.6f}"
        return {
            "map_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}",
            "directions_url": f"https://www.openstreetmap.org/directions?to={lat}%2C{lng}",
            "geo_uri": f"geo:{lat},{lng}?q={lat},{lng}",
        }
    query = quote_plus(address)
    return {
        "map_url": f"https://www.openstreetmap.org/search?query={query}",
        "directions_url": f"https://www.openstreetmap.org/directions?to={query}",
        "geo_uri": f"geo:0,0?q={query}",
    }


def store_location(store) -> dict | None:
    if store is None:
        return None
    address = ", ".join(filter(None, [store.address_line1, store.area, store.city, store.postal_code]))
    return {
        "name": store.name,
        "address": address,
        "phone": store.phone,
        "latitude": str(store.latitude) if store.latitude is not None else None,
        "longitude": str(store.longitude) if store.longitude is not None else None,
        **map_links(store.latitude, store.longitude, address),
    }


CUSTOMER_KEYS = ("name", "phone", "address_line1", "address_line2", "area", "landmark", "city", "postal_code")


def customer_location(order, *, reveal: bool) -> dict:
    """The customer's address and phone are shown to the rider only while the job is active."""
    snap = order.address_snapshot or {}
    if not reveal:
        return {"area": snap.get("area", ""), "city": snap.get("city", "")}
    address = ", ".join(
        filter(None, [snap.get(k) for k in ("address_line1", "address_line2", "area", "city", "postal_code")])
    )
    return {
        **{key: snap.get(key) for key in CUSTOMER_KEYS},
        "address": address,
        "latitude": snap.get("latitude"),
        "longitude": snap.get("longitude"),
        "note": order.customer_note,
        **map_links(snap.get("latitude"), snap.get("longitude"), address),
    }


NEXT_ACTIONS = {
    (KIND.DELIVERY, A.ASSIGNED): ["accept", "reject"],
    (KIND.DELIVERY, A.ACCEPTED): ["pickup", "reject"],
    (KIND.DELIVERY, A.PICKED_UP): ["start", "fail"],
    (KIND.DELIVERY, A.OUT_FOR_DELIVERY): ["proof", "complete", "fail"],
    (KIND.RETURN_PICKUP, A.ASSIGNED): ["accept", "reject"],
    (KIND.RETURN_PICKUP, A.ACCEPTED): ["pickup", "reject", "fail"],
    (KIND.RETURN_PICKUP, A.PICKED_UP): ["proof", "complete", "fail"],
}


class AssignmentSerializer(serializers.ModelSerializer):
    """A job as its rider sees it. Read-only: every change is a dedicated action endpoint."""

    kind_label = serializers.CharField(source="get_kind_display")
    status_label = serializers.CharField(source="get_status_display")
    order_number = serializers.CharField(source="order.order_number")
    order_status = serializers.CharField(source="order.status")
    payment_method = serializers.CharField(source="order.payment_method")
    shipment_sequence = serializers.IntegerField(source="shipment.sequence", default=None)
    return_number = serializers.CharField(source="return_request.return_number", default=None)
    amount_to_collect = serializers.SerializerMethodField()
    cod = serializers.SerializerMethodField()
    pickup = serializers.SerializerMethodField()
    drop = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    otp_state = serializers.SerializerMethodField()
    proof_uploaded = serializers.SerializerMethodField()
    proof_required = serializers.SerializerMethodField()
    next_actions = serializers.SerializerMethodField()
    status_history = DeliveryStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = DeliveryAssignment
        fields = [
            "id",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "order_number",
            "order_status",
            "payment_method",
            "shipment_sequence",
            "return_number",
            "amount_to_collect",
            "cod",
            "pickup",
            "drop",
            "items",
            "otp_state",
            "proof_uploaded",
            "proof_required",
            "received_by",
            "next_actions",
            "assigned_at",
            "accepted_at",
            "picked_up_at",
            "out_for_delivery_at",
            "delivered_at",
            "failed_at",
            "failure_code",
            "failure_reason",
            "rejected_at",
            "reject_reason",
            "distance_km",
            "earning_amount",
            "delivery_notes",
            "status_history",
        ]
        read_only_fields = fields

    def _store(self, obj):
        # The store of this rider's shipment (an order may ship from several stores).
        return obj.shipment.store if obj.shipment_id else obj.order.store

    def get_amount_to_collect(self, obj) -> str | None:
        """Cash to collect at the door for this shipment; null when nothing is due."""
        if obj.kind != KIND.DELIVERY or obj.cod_amount_due <= 0 or obj.cod_collected_at:
            return None
        return str(obj.cod_amount_due)

    def get_cod(self, obj) -> dict | None:
        if obj.cod_amount_due <= 0:
            return None
        return {
            "amount_due": str(obj.cod_amount_due),
            "collected": obj.cod_collected_at is not None,
            "collected_amount": str(obj.cod_collected_amount) if obj.cod_collected_amount is not None else None,
            "method": obj.cod_method or None,
            "collected_at": obj.cod_collected_at,
            "handed_over": obj.cod_handed_over_at is not None,
            "handed_over_at": obj.cod_handed_over_at,
        }

    def get_pickup(self, obj) -> dict | None:
        """Where the rider collects: the store (delivery) or the customer (return pickup)."""
        if obj.kind == KIND.RETURN_PICKUP:
            return customer_location(obj.order, reveal=obj.is_active)
        return store_location(self._store(obj))

    def get_drop(self, obj) -> dict | None:
        """Where the rider hands over: the customer (delivery) or the store (return pickup)."""
        if obj.kind == KIND.RETURN_PICKUP:
            return store_location(self._store(obj))
        return customer_location(obj.order, reveal=obj.is_active)

    def get_items(self, obj) -> list[dict]:
        """What to carry: names and quantities only, never prices."""
        if obj.kind == KIND.RETURN_PICKUP and obj.return_request_id:
            lines = [(line.order_item, line.quantity) for line in obj.return_request.items.all()]
        elif obj.shipment_id:
            lines = [(item, item.quantity) for item in obj.shipment.items.all()]
        else:
            lines = []
        return [
            {"name": item.product_name, "variant": item.variant_name, "sku": item.sku, "quantity": quantity}
            for item, quantity in lines
        ]

    def get_otp_state(self, obj) -> str:
        """none | active | expired | locked | used. The rider never sees the code itself."""
        return otp.state(obj) if obj.kind == KIND.DELIVERY else "none"

    def get_proof_uploaded(self, obj) -> bool:
        return bool(obj.proof_image)

    def get_proof_required(self, obj) -> bool:
        return obj.kind == KIND.DELIVERY and settings.DELIVERY_PROOF_REQUIRED

    def get_next_actions(self, obj) -> list[str]:
        return NEXT_ACTIONS.get((obj.kind, obj.status), [])


class EarningsSerializer(serializers.Serializer):
    delivered_count = serializers.IntegerField()
    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    today_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    last_7_days_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    # Phase 10
    today_delivered_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    cash_in_hand = serializers.DecimalField(max_digits=12, decimal_places=2)
    cash_deliveries_pending_handover = serializers.IntegerField()


# --- Phase 10: what the rider sends --------------------------------------------------------------


class _PositionSerializer(serializers.Serializer):
    """Optional position of the rider at this step (stored in the job's history)."""

    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, min_value=-180, max_value=180)

    def position(self):
        data = self.validated_data
        if "latitude" in data and "longitude" in data:
            return data["latitude"], data["longitude"]
        return None


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class StepSerializer(_PositionSerializer):
    pass


class CompleteDeliverySerializer(_PositionSerializer):
    """The customer's code, and for cash-on-delivery orders what was collected. The amount is
    compared with what the order says; it never sets a price."""

    otp = serializers.CharField(max_length=12, required=False, allow_blank=True, default="")
    cod_collected = serializers.BooleanField(required=False, default=False)
    cod_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    cod_method = serializers.ChoiceField(choices=DeliveryAssignment.CodMethod.choices, required=False)
    cod_reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    received_by = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def cod(self) -> dict:
        data = self.validated_data
        return {
            "collected": data["cod_collected"],
            "amount": data.get("cod_amount"),
            "method": data.get("cod_method"),
            "reference": data["cod_reference"],
        }


class FailDeliverySerializer(_PositionSerializer):
    reason = serializers.ChoiceField(choices=DeliveryAssignment.FailureCode.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class NotesSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=500, allow_blank=True)


class ProofUploadSerializer(serializers.Serializer):
    photo = serializers.ImageField()
    received_by = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


# --- Phase 9: serviceability, estimates, zones, stores, shipments --------------------------------


class LocationQuerySerializer(serializers.Serializer):
    """Where to deliver: a saved address (signed in), map coordinates, or just a PIN code."""

    address_id = serializers.IntegerField(required=False, min_value=1)
    postal_code = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, min_value=-180, max_value=180)

    def validate(self, attrs):
        if ("latitude" in attrs) != ("longitude" in attrs):
            raise serializers.ValidationError("Send both latitude and longitude.")
        if not (attrs.get("address_id") or attrs.get("postal_code") or "latitude" in attrs):
            raise serializers.ValidationError("Send an address_id, a postal_code or latitude/longitude.")
        return attrs


class ProductEstimateQuerySerializer(LocationQuerySerializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=999, default=1)


class ZoneSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name")
    store_area = serializers.CharField(source="store.area")
    city = serializers.CharField(source="store.city")
    postal_codes = serializers.SerializerMethodField()
    delivery_fee = serializers.SerializerMethodField()
    free_delivery_min_order = serializers.SerializerMethodField()
    fast_delivery_max_minutes = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryZone
        fields = [
            "id",
            "name",
            "store_name",
            "store_area",
            "city",
            "radius_km",
            "postal_codes",
            "fast_delivery_enabled",
            "fast_delivery_max_minutes",
            "delivery_fee",
            "free_delivery_min_order",
        ]

    def get_postal_codes(self, obj) -> list[str]:
        return sorted(obj.postal_code_set)

    def get_delivery_fee(self, obj) -> str:
        from .fulfillment import FeeRule

        return str(FeeRule.for_zone(obj).fee)

    def get_free_delivery_min_order(self, obj) -> str:
        from .fulfillment import FeeRule

        return str(FeeRule.for_zone(obj).free_min)

    def get_fast_delivery_max_minutes(self, obj) -> int:
        from django.conf import settings

        return obj.fast_delivery_max_minutes or settings.FAST_DELIVERY_MAX_MINUTES


class _NearbyStoreSerializer(serializers.Serializer):
    name = serializers.CharField()
    area = serializers.CharField()
    distance_km = serializers.FloatField(allow_null=True)
    fast_available = serializers.BooleanField()
    eta_minutes = serializers.IntegerField()
    label = serializers.CharField()


class ServiceabilitySerializer(serializers.Serializer):
    serviceable = serializers.BooleanField()
    postal_code = serializers.CharField(allow_blank=True)
    location_precision = serializers.CharField(help_text="exact | pin | unknown")
    fast_delivery_available = serializers.BooleanField()
    label = serializers.CharField(
        help_text="Best indicative estimate for an in-stock item, e.g. 'Delivery in 32 minutes'."
    )
    fast_unavailable_reason = serializers.CharField()
    message = serializers.CharField()
    stores = _NearbyStoreSerializer(many=True)


class StoreAvailabilitySerializer(serializers.Serializer):
    store_name = serializers.CharField()
    store_area = serializers.CharField()
    city = serializers.CharField()
    kind = serializers.CharField()
    stock_status = serializers.CharField(help_text="in_stock | low_stock | out_of_stock (no exact quantities)")
    delivers_to_location = serializers.BooleanField(allow_null=True, help_text="null when no location was sent")
    distance_km = serializers.FloatField(allow_null=True)


def latest_delivery(shipment) -> DeliveryAssignment | None:
    """The delivery job that tells this shipment's story: the active one, else the last one a
    rider really worked on (prefetched `assignments`, newest first)."""
    jobs = [a for a in shipment.assignments.all() if a.kind == KIND.DELIVERY]
    for job in jobs:
        if job.status in DeliveryAssignment.ACTIVE_STATUSES:
            return job
    for job in jobs:
        if job.status in (A.DELIVERED, A.FAILED):
            return job
    return None


def cod_summary(job: DeliveryAssignment | None) -> dict | None:
    if job is None or job.cod_amount_due <= 0:
        return None
    return {
        "amount_due": str(job.cod_amount_due),
        "collected": job.cod_collected_at is not None,
        "method": job.cod_method or None,
        "reference": job.cod_reference,
        "collected_at": job.cod_collected_at,
        "handed_over": job.cod_handed_over_at is not None,
        "handed_over_at": job.cod_handed_over_at,
    }


class StaffShipmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order_number = serializers.CharField(source="order.order_number")
    order_status = serializers.CharField(source="order.status")
    payment_method = serializers.CharField(source="order.payment_method")
    sequence = serializers.IntegerField()
    store_name = serializers.CharField(source="store.name")
    status = serializers.CharField()
    status_label = serializers.CharField(source="get_status_display")
    delivery_type = serializers.CharField()
    distance_km = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    estimated_ready_at = serializers.DateTimeField(allow_null=True)
    estimated_delivery_at = serializers.DateTimeField(allow_null=True)
    delivery_attempts = serializers.IntegerField()
    picked_up_at = serializers.DateTimeField(allow_null=True)
    out_for_delivery_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    failed_at = serializers.DateTimeField(allow_null=True)
    failure_reason = serializers.CharField()
    failure_note = serializers.CharField()
    assigned_partner = serializers.SerializerMethodField()
    rider = serializers.SerializerMethodField()
    cod = serializers.SerializerMethodField()
    proof_available = serializers.SerializerMethodField()
    can_assign = serializers.SerializerMethodField()
    can_reassign = serializers.SerializerMethodField()

    def _active(self, obj):
        jobs = [a for a in obj.assignments.all() if a.kind == KIND.DELIVERY]
        return next((a for a in jobs if a.status in DeliveryAssignment.ACTIVE_STATUSES), None)

    def get_assigned_partner(self, obj) -> str | None:
        active = self._active(obj)
        return active.partner.user.full_name if active else None

    def get_rider(self, obj) -> dict | None:
        job = latest_delivery(obj)
        if job is None:
            return None
        return {
            "assignment_id": job.pk,
            "assignment_status": job.status,
            "partner_id": job.partner_id,
            "full_name": job.partner.user.full_name,
            "phone": job.partner.phone,
            "completed_without_otp": job.completed_without_otp,
        }

    def get_cod(self, obj) -> dict | None:
        return cod_summary(latest_delivery(obj))

    def get_proof_available(self, obj) -> bool:
        job = latest_delivery(obj)
        return bool(job and job.proof_image)

    def get_can_assign(self, obj) -> bool:
        from .assignment import ASSIGNABLE_ORDER_STATUSES, ASSIGNABLE_SHIPMENT_STATUSES

        return (
            self._active(obj) is None
            and obj.status in ASSIGNABLE_SHIPMENT_STATUSES
            and obj.order.status in ASSIGNABLE_ORDER_STATUSES
        )

    def get_can_reassign(self, obj) -> bool:
        active = self._active(obj)
        return bool(active and active.status in DeliveryAssignment.BEFORE_PICKUP)


class StaffAssignmentSerializer(serializers.ModelSerializer):
    """One rider's job on a shipment, for the store's delivery history."""

    partner_name = serializers.CharField(source="partner.user.full_name")
    kind_label = serializers.CharField(source="get_kind_display")
    status_label = serializers.CharField(source="get_status_display")
    proof_available = serializers.SerializerMethodField()
    status_history = DeliveryStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = DeliveryAssignment
        fields = [
            "id",
            "kind",
            "kind_label",
            "status",
            "status_label",
            "partner_id",
            "partner_name",
            "assigned_at",
            "accepted_at",
            "picked_up_at",
            "out_for_delivery_at",
            "delivered_at",
            "failed_at",
            "failure_code",
            "failure_reason",
            "rejected_at",
            "reject_reason",
            "received_by",
            "completed_without_otp",
            "otp_verified_at",
            "delivery_notes",
            "proof_available",
            "cod_amount_due",
            "cod_collected_amount",
            "cod_method",
            "cod_collected_at",
            "cod_handed_over_at",
            "earning_amount",
            "status_history",
        ]

    def get_proof_available(self, obj) -> bool:
        return bool(obj.proof_image)


class StaffShipmentDetailSerializer(StaffShipmentSerializer):
    items = serializers.SerializerMethodField()
    assignments = serializers.SerializerMethodField()

    def get_items(self, obj) -> list[dict]:
        return [
            {"name": i.product_name, "variant": i.variant_name, "sku": i.sku, "quantity": i.quantity}
            for i in obj.items.all()
        ]

    def get_assignments(self, obj) -> list[dict]:
        return StaffAssignmentSerializer(obj.assignments.all(), many=True).data


class PartnerAvailabilitySerializer(serializers.Serializer):
    """Riders as the store sees them: who is online, how loaded, how much cash they carry."""

    partner_id = serializers.IntegerField(source="pk")
    full_name = serializers.CharField(source="user.full_name")
    phone = serializers.CharField()
    vehicle_type = serializers.CharField()
    home_store_name = serializers.CharField(source="home_store.name", default=None)
    status = serializers.CharField()
    is_verified = serializers.BooleanField()
    is_active = serializers.BooleanField()
    active_assignments = serializers.IntegerField(source="active_count")
    capacity = serializers.IntegerField(source="max_active_assignments")
    can_take_jobs = serializers.SerializerMethodField()
    cash_in_hand = serializers.SerializerMethodField()
    last_location_at = serializers.DateTimeField(allow_null=True)

    def get_can_take_jobs(self, obj) -> bool:
        return (
            obj.is_active
            and obj.is_verified
            and obj.status == DeliveryPartner.Status.AVAILABLE
            and obj.active_count < obj.max_active_assignments
        )

    def get_cash_in_hand(self, obj) -> str:
        return str(self.context.get("cash", {}).get(obj.pk, "0.00"))


class CodCollectionSerializer(serializers.ModelSerializer):
    assignment_id = serializers.IntegerField(source="pk")
    order_number = serializers.CharField(source="order.order_number")
    store_name = serializers.CharField(source="shipment.store.name", default=None)
    partner_id = serializers.IntegerField()
    partner_name = serializers.CharField(source="partner.user.full_name")
    handed_over = serializers.SerializerMethodField()
    handed_over_to = serializers.CharField(source="cod_handed_over_to.full_name", default=None)

    class Meta:
        model = DeliveryAssignment
        fields = [
            "assignment_id",
            "order_number",
            "store_name",
            "partner_id",
            "partner_name",
            "cod_amount_due",
            "cod_collected_amount",
            "cod_method",
            "cod_reference",
            "cod_collected_at",
            "handed_over",
            "cod_handed_over_at",
            "handed_over_to",
            "cod_handover_note",
        ]

    def get_handed_over(self, obj) -> bool:
        return obj.cod_handed_over_at is not None


class ReassignSerializer(serializers.Serializer):
    partner_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class UnassignSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CompleteWithoutOtpSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=200)
    cod_collected = serializers.BooleanField(required=False, default=False)
    cod_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    cod_method = serializers.ChoiceField(choices=DeliveryAssignment.CodMethod.choices, required=False)
    cod_reference = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")


class HandoverSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class EligiblePartnerSerializer(serializers.Serializer):
    partner_id = serializers.IntegerField(source="partner.pk")
    full_name = serializers.CharField(source="partner.user.full_name")
    vehicle_type = serializers.CharField(source="partner.vehicle_type")
    same_store = serializers.BooleanField()
    active_assignments = serializers.IntegerField()
    capacity = serializers.IntegerField(source="partner.max_active_assignments")
    distance_km = serializers.FloatField(allow_null=True)


class AssignShipmentSerializer(serializers.Serializer):
    partner_id = serializers.IntegerField(min_value=1)
