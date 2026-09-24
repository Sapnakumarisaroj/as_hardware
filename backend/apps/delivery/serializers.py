from rest_framework import serializers

from .models import DeliveryAssignment, DeliveryPartner, DeliveryStatusHistory


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
        store = obj.order.store
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
