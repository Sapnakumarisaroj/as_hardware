from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.validators import normalize_phone, phone_validator

from .models import Address


class AddressSerializer(serializers.ModelSerializer):
    # Accept common formats ("+91 98765 43210"); normalised, then validated, in validate_phone.
    phone = serializers.CharField(max_length=20)

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["country", "created_at", "updated_at"]

    def validate_phone(self, value):
        normalized = normalize_phone(value)
        try:
            phone_validator(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return normalized

    def validate(self, attrs):
        lat, lng = attrs.get("latitude"), attrs.get("longitude")
        if (lat is None) != (lng is None) and not self.partial:
            raise serializers.ValidationError("Provide both latitude and longitude, or neither.")
        return attrs
