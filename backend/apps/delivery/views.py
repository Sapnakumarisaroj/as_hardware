"""Delivery-partner self-service (own data only). The assignment workflow — accept, pickup,
OTP, proof of delivery — arrives in Phase 10."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError
from apps.core.permissions import IsDeliveryPartner

from .models import DeliveryAssignment, DeliveryPartner
from .serializers import AssignmentSerializer, AvailabilitySerializer, DeliveryPartnerSerializer, EarningsSerializer


class DeliveryMeView(APIView):
    permission_classes = [IsDeliveryPartner]

    @extend_schema(responses=DeliveryPartnerSerializer)
    def get(self, request):
        return Response(DeliveryPartnerSerializer(request.user.delivery_partner).data)

    @extend_schema(request=AvailabilitySerializer, responses=DeliveryPartnerSerializer)
    def patch(self, request):
        partner = request.user.delivery_partner
        serializer = AvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        if new_status == DeliveryPartner.Status.AVAILABLE and not (partner.is_active and partner.is_verified):
            raise ConflictError(
                "Your partner account must be verified by an admin before going online.", code="partner_not_verified"
            )
        if partner.assignments.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).exists():
            raise ConflictError("Finish your active delivery before changing availability.", code="active_delivery")
        if partner.status != new_status:
            partner.status = new_status
            partner.save(update_fields=["status", "updated_at"])
            record_audit(
                action="delivery.availability",
                actor=request.user,
                target=partner,
                changes={"status": new_status},
                request=request,
            )
        return Response(DeliveryPartnerSerializer(partner).data)


@extend_schema_view(list=extend_schema(parameters=[OpenApiParameter("scope", str, enum=["active", "history"])]))
class AssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsDeliveryPartner]
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryAssignment.objects.none()
        qs = (
            DeliveryAssignment.objects.filter(partner__user=self.request.user)
            .select_related("order__store", "shipment__store")
            .prefetch_related("status_history")
        )
        scope = self.request.query_params.get("scope")
        if scope == "active":
            qs = qs.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES)
        elif scope == "history":
            qs = qs.exclude(status__in=DeliveryAssignment.ACTIVE_STATUSES)
        return qs


class EarningsView(APIView):
    permission_classes = [IsDeliveryPartner]

    @extend_schema(responses=EarningsSerializer)
    def get(self, request):
        now = timezone.now()
        # Explicit range instead of `__date`: MySQL needs timezone tables for tz-aware __date lookups,
        # which shared hosts often don't load.
        start_of_today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        delivered = Q(status=DeliveryAssignment.Status.DELIVERED)
        agg = DeliveryAssignment.objects.filter(partner__user=request.user).aggregate(
            delivered_count=Count("id", filter=delivered),
            total=Sum("earning_amount", filter=delivered),
            today=Sum("earning_amount", filter=delivered & Q(delivered_at__gte=start_of_today)),
            week=Sum("earning_amount", filter=delivered & Q(delivered_at__gte=now - timedelta(days=7))),
        )
        zero = Decimal("0.00")
        return Response(
            EarningsSerializer(
                {
                    "delivered_count": agg["delivered_count"],
                    "total_earnings": agg["total"] or zero,
                    "today_earnings": agg["today"] or zero,
                    "last_7_days_earnings": agg["week"] or zero,
                }
            ).data
        )
