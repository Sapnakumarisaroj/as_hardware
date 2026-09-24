from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.serializers import OrderDetailSerializer
from apps.orders.views import OrderViewSet

from . import services


class VerifyPaymentSerializer(serializers.Serializer):
    """Whatever the gateway returned to the browser. The provider verifies it server-side.

    Mock provider: {"mock_signature": <from client_payload>, "mock_outcome": "success"|"failed"|"cancelled"}.
    """

    payload = serializers.DictField()


class VerifyPaymentView(APIView):
    """Verify an online payment for the signed-in customer's own order; returns the updated order."""

    @extend_schema(request=VerifyPaymentSerializer, responses=OrderDetailSerializer)
    def post(self, request, public_id):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.verify_payment(public_id, user=request.user, payload=serializer.validated_data["payload"])
        viewset = OrderViewSet(request=request, action="retrieve", format_kwarg=None)
        order = viewset.get_queryset().get(pk=payment.order_id)
        return Response(OrderDetailSerializer(order, context={"request": request}).data)
