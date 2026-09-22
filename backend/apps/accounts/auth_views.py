from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError

from . import auth_services
from .auth_serializers import (
    AuthResponseSerializer,
    AvatarSerializer,
    ChangePasswordSerializer,
    DeactivateSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    MeSerializer,
    ProfileSerializer,
    RefreshSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
)
from .models import CustomerProfile

DetailSerializer = inline_serializer("Detail", {"detail": serializers.CharField()})


def _auth_response(user, request, status_code=status.HTTP_200_OK):
    tokens = auth_services.issue_tokens(user)
    body = {**tokens, "user": MeSerializer(user, context={"request": request}).data}
    return Response(body, status=status_code)


class _PublicAuthView(APIView):
    """Unauthenticated endpoints, rate limited per client IP (scope `auth`)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(_PublicAuthView):
    @extend_schema(request=RegisterSerializer, responses={201: AuthResponseSerializer})
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = auth_services.register_customer(
            email=data["email"], password=data["password"], full_name=data["full_name"], phone=data["phone"],
            request=request,
        )
        return _auth_response(user, request, status.HTTP_201_CREATED)


class LoginView(_PublicAuthView):
    @extend_schema(request=LoginSerializer, responses=AuthResponseSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = auth_services.login(request=request, **serializer.validated_data)
        return _auth_response(user, request)


class RefreshView(TokenRefreshView):
    """Rotates the refresh token (old one blacklisted). Rejects inactive users and pre-password-change tokens."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class LogoutView(_PublicAuthView):
    @extend_schema(request=RefreshSerializer, responses={205: None})
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_services.logout(serializer.validated_data["refresh"], request=request)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class ForgotPasswordView(_PublicAuthView):
    @extend_schema(request=ForgotPasswordSerializer, responses=DetailSerializer)
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_services.request_password_reset(email=serializer.validated_data["email"], request=request)
        return Response(
            {"detail": "If an account exists for that email, we've sent a link to reset the password."}
        )


class ResetPasswordView(_PublicAuthView):
    @extend_schema(request=ResetPasswordSerializer, responses=DetailSerializer)
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        auth_services.reset_password(uid=data["uid"], token=data["token"], new_password=data["password"],
                                     request=request)
        return Response({"detail": "Your password has been reset. You can now log in."})


class ChangePasswordView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=ChangePasswordSerializer, responses=AuthResponseSerializer)
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tokens = auth_services.change_password(
            request.user, current_password=data["current_password"], new_password=data["new_password"],
            request=request,
        )
        return Response({**tokens, "user": MeSerializer(request.user, context={"request": request}).data})


class MeView(APIView):
    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user, context={"request": request}).data)


class ProfileView(APIView):
    """The signed-in user's own profile. There is no way to read another user's profile here."""

    permission_classes = [IsAuthenticated]

    def _profile_user(self, request):
        CustomerProfile.objects.get_or_create(user=request.user)
        return request.user

    @extend_schema(responses=ProfileSerializer)
    def get(self, request):
        return Response(ProfileSerializer(self._profile_user(request), context={"request": request}).data)

    @extend_schema(request=ProfileSerializer, responses=ProfileSerializer)
    @transaction.atomic
    def patch(self, request):
        user = self._profile_user(request)
        serializer = ProfileSerializer(user, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("current_password", None)
        prefs = data.pop("profile", {})
        changed = []
        for field in ("email", "full_name", "phone"):
            if field in data:
                value = data[field] or (None if field == "phone" else "")
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed.append(field)
        if "email" in changed:
            user.email_verified = False  # a new address must be verified again (verification: later phase)
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError as exc:  # concurrent duplicate email/phone
            raise ConflictError(
                "That email or phone is already used by another account.", code="account_exists"
            ) from exc
        for field, value in prefs.items():
            setattr(user.profile, field, value)
        user.profile.save()
        if changed:
            record_audit(action="profile.update", actor=user, target=user, request=request,
                         changes={"fields": sorted(set(changed))})
        return Response(ProfileSerializer(user, context={"request": request}).data)


class AvatarView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request={"multipart/form-data": AvatarSerializer}, responses=ProfileSerializer)
    def post(self, request):
        serializer = AvatarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
        profile.avatar.field.run_validators(serializer.validated_data["avatar"])
        if profile.avatar:
            profile.avatar.delete(save=False)
        profile.avatar = serializer.validated_data["avatar"]
        profile.save()
        return Response(ProfileSerializer(request.user, context={"request": request}).data)

    @extend_schema(responses=ProfileSerializer)
    def delete(self, request):
        profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
        if profile.avatar:
            profile.avatar.delete(save=True)
        return Response(ProfileSerializer(request.user, context={"request": request}).data)


class DeactivateAccountView(APIView):
    @extend_schema(request=DeactivateSerializer, responses={204: None})
    def post(self, request):
        serializer = DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_services.deactivate_account(request.user, request=request, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)
