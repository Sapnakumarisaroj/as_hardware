from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import Address
from .serializers import AddressSerializer


class AddressViewSet(viewsets.ModelViewSet):
    """The signed-in customer's delivery addresses. Other users' addresses are invisible (404)."""

    serializer_class = AddressSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Address.objects.none()
        return Address.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = services.create_address(user=request.user, **serializer.validated_data)
        return Response(AddressSerializer(address).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        address = services.update_address(instance, **serializer.validated_data)
        return Response(AddressSerializer(address).data)

    def perform_destroy(self, instance):
        services.delete_address(instance)

    @extend_schema(request=None, responses=AddressSerializer)
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        address = services.set_default_address(self.get_object())
        return Response(AddressSerializer(address).data)
