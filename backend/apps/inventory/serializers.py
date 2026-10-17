from rest_framework import serializers

from apps.catalog.models import ProductVariant
from apps.stores.models import Store

from .models import Inventory, StockMovement


class InventorySerializer(serializers.ModelSerializer):
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    product_name = serializers.CharField(source="variant.product.name", read_only=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "id",
            "store",
            "store_code",
            "store_name",
            "variant",
            "sku",
            "product_name",
            "variant_name",
            "available_quantity",
            "reserved_quantity",
            "low_stock_threshold",
            "is_low_stock",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["store", "variant", "available_quantity", "reserved_quantity"]


class InventoryCreateSerializer(serializers.ModelSerializer):
    """Create a stock record; opening stock is booked as a 'purchase' movement, never set directly."""

    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all())
    opening_quantity = serializers.IntegerField(min_value=0, default=0, write_only=True)

    class Meta:
        model = Inventory
        fields = ["store", "variant", "low_stock_threshold", "is_active", "opening_quantity"]

    def validate(self, attrs):
        if Inventory.objects.filter(store=attrs["store"], variant=attrs["variant"]).exists():
            raise serializers.ValidationError("This store already has a stock record for this variant.")
        return attrs


class StockAdjustSerializer(serializers.Serializer):
    MANUAL_TYPES = [StockMovement.Type.PURCHASE, StockMovement.Type.ADJUSTMENT, StockMovement.Type.RETURN]

    movement_type = serializers.ChoiceField(choices=MANUAL_TYPES)
    quantity = serializers.IntegerField()
    # Every manual change says why, so the stock history can be understood later.
    reason = serializers.CharField(max_length=255)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError("Quantity cannot be zero.")
        return value


class StockMovementSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="inventory.variant.sku", read_only=True)
    store_code = serializers.CharField(source="inventory.store.code", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "inventory",
            "sku",
            "store_code",
            "movement_type",
            "quantity",
            "available_after",
            "reserved_after",
            "reason",
            "reference_type",
            "reference_id",
            "created_by",
            "created_at",
        ]
