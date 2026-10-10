from django.contrib.auth import get_user_model
from rest_framework import serializers

from .auth_services import validate_new_password
from .models import CustomerProfile
from .serializers import GSTINField, PhoneField

User = get_user_model()


def _password_field(**kwargs):
    return serializers.CharField(write_only=True, trim_whitespace=False, max_length=128, **kwargs)


class RegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(min_length=2, max_length=150)
    email = serializers.EmailField(max_length=254)
    phone = PhoneField()
    password = _password_field()
    password_confirm = _password_field()

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists. Try logging in.")
        return value

    def validate_phone(self, value):
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": ["Passwords do not match."]})
        # Similarity check needs the would-be user's details.
        validate_new_password(attrs["password"], User(email=attrs["email"], full_name=attrs["full_name"]))
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254)
    password = _password_field()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)
    password = _password_field()
    password_confirm = _password_field()

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": ["Passwords do not match."]})
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = _password_field()
    new_password = _password_field()
    new_password_confirm = _password_field()

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": ["Passwords do not match."]})
        return attrs


class DeactivateSerializer(serializers.Serializer):
    password = _password_field()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ManagedStoreSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()


class MeSerializer(serializers.ModelSerializer):
    """Safe identity data for the signed-in user (what the frontend auth state needs)."""

    avatar = serializers.SerializerMethodField()
    managed_stores = serializers.SerializerMethodField()
    buyer_type = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "email_verified",
            "avatar",
            "managed_stores",
            "buyer_type",
        ]

    def get_buyer_type(self, obj) -> str:
        profile = getattr(obj, "profile", None)
        return profile.buyer_type if profile else CustomerProfile.BuyerType.INDIVIDUAL

    def get_avatar(self, obj) -> str | None:
        profile = getattr(obj, "profile", None)
        if not profile or not profile.avatar:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(profile.avatar.url) if request else profile.avatar.url

    def get_managed_stores(self, obj) -> list[dict]:
        if obj.role != User.Role.STORE_MANAGER:
            return []
        return ManagedStoreSerializer(obj.managed_stores.order_by("name"), many=True).data


class AuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = MeSerializer()


class ProfileSerializer(serializers.Serializer):
    """Editable profile. Role/status are never writable here."""

    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(max_length=254, required=False)
    current_password = _password_field(required=False, help_text="Required when changing the email address.")
    full_name = serializers.CharField(min_length=2, max_length=150, required=False)
    phone = PhoneField(required=False)
    role = serializers.CharField(read_only=True)
    email_verified = serializers.BooleanField(read_only=True)
    date_joined = serializers.DateTimeField(read_only=True)
    avatar = serializers.SerializerMethodField()
    preferred_language = serializers.ChoiceField(
        choices=CustomerProfile.Language.choices, source="profile.preferred_language", required=False
    )
    marketing_opt_in = serializers.BooleanField(source="profile.marketing_opt_in", required=False)
    whatsapp_opt_in = serializers.BooleanField(source="profile.whatsapp_opt_in", required=False)
    personalization_opt_in = serializers.BooleanField(source="profile.personalization_opt_in", required=False)
    # Professional buying (self-declared). GSTIN: format + check character only, never looked up.
    buyer_type = serializers.ChoiceField(
        choices=CustomerProfile.BuyerType.choices, source="profile.buyer_type", required=False
    )
    business_name = serializers.CharField(
        max_length=150, source="profile.business_name", required=False, allow_blank=True
    )
    gstin = GSTINField(source="profile.gstin", required=False)

    def get_avatar(self, obj) -> str | None:
        return MeSerializer(obj, context=self.context).get_avatar(obj)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("This email is already used by another account.")
        return value

    def validate_phone(self, value):
        if value and User.objects.filter(phone=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("This phone number is already used by another account.")
        return value

    def validate(self, attrs):
        new_email = attrs.get("email")
        if new_email and new_email != self.instance.email:
            password = attrs.get("current_password") or ""
            if not self.instance.check_password(password):
                raise serializers.ValidationError(
                    {"current_password": ["Enter your current password to change your email."]}
                )
        return attrs


class AvatarSerializer(serializers.Serializer):
    avatar = serializers.ImageField()


class AdminUserSerializer(serializers.ModelSerializer):
    managed_stores = ManagedStoreSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "is_active",
            "email_verified",
            "date_joined",
            "last_login",
            "deactivated_at",
            "managed_stores",
        ]
        read_only_fields = fields


class AdminUserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = PhoneField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
    managed_store_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False)
