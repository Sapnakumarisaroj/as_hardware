"""JWT authentication hardened for this project.

On top of SimpleJWT's checks (signature, expiry, user exists, user active):
- tokens issued *before* the user's last password change/reset are rejected, so a
  password change immediately logs out every other session (access tokens included);
- the refresh endpoint re-checks the account (active, password not changed since issue).
"""

from django.contrib.auth import get_user_model
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework_simplejwt.authentication import JWTAuthentication as BaseJWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer as BaseTokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken


def issued_before_password_change(user, token) -> bool:
    changed = getattr(user, "password_changed_at", None)
    issued_at = token.get("iat")
    if not changed or issued_at is None:
        return False
    # Compare at whole-second precision (JWT `iat` is an integer).
    return int(issued_at) < int(changed.timestamp())


class JWTAuthentication(BaseJWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)  # raises if missing/inactive
        if issued_before_password_change(user, validated_token):
            raise InvalidToken({"detail": "Session expired. Please log in again.", "code": "token_not_valid"})
        return user


class TokenRefreshSerializer(BaseTokenRefreshSerializer):
    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        user = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
        if user is None or not user.is_active or issued_before_password_change(user, refresh):
            raise AuthenticationFailed("Session expired. Please log in again.", code="token_not_valid")
        return super().validate(attrs)


class JWTAuthenticationScheme(SimpleJWTScheme):
    """OpenAPI docs: describe the subclass as the same Bearer `jwtAuth` scheme as SimpleJWT's."""

    target_class = JWTAuthentication
