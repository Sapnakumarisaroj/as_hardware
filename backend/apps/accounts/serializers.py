from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.validators import gstin_validator, normalize_phone, phone_validator

from .models import Address


class PhoneField(serializers.CharField):
    """Accepts common formats ("+91 98765 43210", "098765-43210") and stores the bare 10 digits."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not value:
            return value
        normalized = normalize_phone(value)
        try:
            phone_validator(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return normalized


class GSTINField(serializers.CharField):
    """Optional GSTIN, stored upper-case. Checks the official format and check character only."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault("allow_blank", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = "".join(super().to_internal_value(data).split()).upper()
        if not value:
            return ""
        try:
            gstin_validator(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value


class AddressSerializer(serializers.ModelSerializer):
    phone = PhoneField()
    business_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    gstin = GSTINField(required=False)

    class Meta:
        model = Address
        fields = [
            "id",
            "name",
            "phone",
            "address_line1",
            "address_line2",
            "area",
            "landmark",
            "city",
            "state",
            "postal_code",
            "country",
            "latitude",
            "longitude",
            "address_type",
            "is_default",
            "business_name",
            "gstin",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["country", "created_at", "updated_at"]

    def validate(self, attrs):
        # Every delivery address needs its map pin: the delivery distance (and fee) is measured to it.
        # An edit must leave a pin in place, so an old address without one is completed when it is edited.
        instance = self.instance
        lat = attrs["latitude"] if "latitude" in attrs else getattr(instance, "latitude", None)
        lng = attrs["longitude"] if "longitude" in attrs else getattr(instance, "longitude", None)
        if lat is None or lng is None:
            raise serializers.ValidationError(
                {"location": ["Select your delivery location on the map (drop the pin on your building)."]}
            )
        return attrs
