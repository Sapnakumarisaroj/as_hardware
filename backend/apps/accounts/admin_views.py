from django.contrib.auth import get_user_model
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.response import Response

from apps.core.permissions import IsAdminRole

from . import admin_services
from .auth_serializers import AdminUserSerializer, AdminUserUpdateSerializer

User = get_user_model()


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Email, name or phone"),
            OpenApiParameter("role", str),
            OpenApiParameter("is_active", bool),
        ]
    )
)
class AdminUserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Admin-only user management. Passwords/tokens are never exposed; roles change only here."""

    permission_classes = [IsAdminRole]
    serializer_class = AdminUserSerializer

    def get_queryset(self):
        qs = User.objects.prefetch_related("managed_stores").order_by("-date_joined")
        params = self.request.query_params
        if term := (params.get("q") or "").strip():
            qs = qs.filter(Q(email__icontains=term) | Q(full_name__icontains=term) | Q(phone__icontains=term))
        if role := params.get("role"):
            qs = qs.filter(role=role)
        if (active := params.get("is_active")) in ("true", "false"):
            qs = qs.filter(is_active=active == "true")
        return qs

    @extend_schema(request=AdminUserUpdateSerializer, responses=AdminUserSerializer)
    def partial_update(self, request, pk=None):
        target = self.get_object()
        serializer = AdminUserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = admin_services.update_user(target, actor=request.user, request=request, **serializer.validated_data)
        return Response(AdminUserSerializer(User.objects.prefetch_related("managed_stores").get(pk=user.pk)).data)
