from rest_framework import serializers

from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory, DeliveryZone


class DeliveryPartnerSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    home_store_name = serializers.CharField(source="home_store.name", read_only=True, default=None)

    class Meta:
        model = DeliveryPartner
        fields = [
            "full_name",
            "phone",
            "vehicle_type",
            "vehicle_number",
            "home_store_name",
            "status",
            "is_verified",
            "is_active",
            "last_location_at",
        ]
        read_only_fields = [f for f in fields if f != "status"]


class AvailabilitySerializer(serializers.Serializer):
    # "busy" is set by the system when an assignment is active, never by the partner.
    status = serializers.ChoiceField(choices=[DeliveryPartner.Status.OFFLINE, DeliveryPartner.Status.AVAILABLE])


class DeliveryStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryStatusHistory
        fields = ["from_status", "to_status", "note", "created_at"]


class AssignmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number")
    order_status = serializers.CharField(source="order.status")
    payment_method = serializers.CharField(source="order.payment_method")
    amount_to_collect = serializers.SerializerMethodField()
    pickup = serializers.SerializerMethodField()
    drop = serializers.SerializerMethodField()
    status_history = DeliveryStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = DeliveryAssignment
        fields = [
            "id",
            "status",
            "order_number",
            "order_status",
            "payment_method",
            "amount_to_collect",
            "pickup",
            "drop",
            "assigned_at",
            "accepted_at",
            "picked_up_at",
            "out_for_delivery_at",
            "delivered_at",
            "distance_km",
            "earning_amount",
            "delivery_notes",
            "status_history",
        ]

    def get_amount_to_collect(self, obj) -> str | None:
        return str(obj.order.grand_total) if obj.order.payment_method == "cod" else None

    def get_pickup(self, obj) -> dict | None:
        # The store this rider collects from: the shipment's (an order may ship from several stores).
        store = obj.shipment.store if obj.shipment_id else obj.order.store
        if store is None:
            return None
        return {
            "name": store.name,
            "address": ", ".join(filter(None, [store.address_line1, store.area, store.city])),
            "phone": store.phone,
            "latitude": str(store.latitude) if store.latitude else None,
            "longitude": str(store.longitude) if store.longitude else None,
        }

    def get_drop(self, obj) -> dict:
        snap = obj.order.address_snapshot or {}
        # Privacy: the customer's contact details are shown only while the delivery is active.
        if obj.status not in DeliveryAssignment.ACTIVE_STATUSES:
            return {"area": snap.get("area", ""), "city": snap.get("city", "")}
        return {
            key: snap.get(key)
            for key in (
                "name",
                "phone",
                "address_line1",
                "address_line2",
                "area",
                "landmark",
                "city",
                "postal_code",
                "latitude",
                "longitude",
            )
        }


class EarningsSerializer(serializers.Serializer):
    delivered_count = serializers.IntegerField()
    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    today_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    last_7_days_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)


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


class StaffShipmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order_number = serializers.CharField(source="order.order_number")
    order_status = serializers.CharField(source="order.status")
    sequence = serializers.IntegerField()
    store_name = serializers.CharField(source="store.name")
    delivery_type = serializers.CharField()
    distance_km = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    estimated_ready_at = serializers.DateTimeField(allow_null=True)
    estimated_delivery_at = serializers.DateTimeField(allow_null=True)
    assigned_partner = serializers.SerializerMethodField()

    def get_assigned_partner(self, obj) -> str | None:
        active = [a for a in obj.assignments.all() if a.status in DeliveryAssignment.ACTIVE_STATUSES]
        return active[0].partner.user.full_name if active else None


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
