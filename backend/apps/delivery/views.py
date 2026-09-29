"""The delivery partner's own API (Phase 3: profile and lists; Phase 10: the workflow).

Every endpoint is limited to the signed-in rider's own jobs: another rider's job is "not
found". Nothing here can change an order's items, prices or customer; each action is a
fixed step validated by apps.delivery.workflow.
"""

import mimetypes
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError
from apps.core.permissions import IsDeliveryPartner
from apps.orders.models import OrderItem, ReturnItem

from . import workflow
from .cod import cash_in_hand, cash_not_handed_over
from .models import DeliveryAssignment, DeliveryPartner
from .serializers import (
    AssignmentSerializer,
    AvailabilitySerializer,
    CompleteDeliverySerializer,
    DeliveryPartnerSerializer,
    EarningsSerializer,
    FailDeliverySerializer,
    LocationPingSerializer,
    NotesSerializer,
    ProofUploadSerializer,
    RejectSerializer,
    StepSerializer,
)


def proof_response(assignment: DeliveryAssignment) -> FileResponse:
    """Stream a proof-of-delivery photo. The caller has already checked who is asking."""
    if not assignment.proof_image:
        raise NotFoundError("No photo was uploaded for this delivery.")
    try:
        handle = assignment.proof_image.open("rb")
    except FileNotFoundError:
        raise NotFoundError("No photo was uploaded for this delivery.") from None
    content_type = mimetypes.guess_type(assignment.proof_image.name)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="delivery-proof-{assignment.pk}.jpg"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def assignment_queryset():
    return DeliveryAssignment.objects.select_related(
        "order", "order__store", "shipment__store", "partner__user", "return_request"
    ).prefetch_related(
        "status_history",
        Prefetch("shipment__items", queryset=OrderItem.objects.order_by("id")),
        Prefetch("return_request__items", queryset=ReturnItem.objects.select_related("order_item")),
    )


def _me(request, *, lock: bool = False) -> DeliveryPartner:
    """The rider's own record, read now (staff may have changed it) and locked when it is about
    to change (an assignment may be arriving at the same moment)."""
    partners = DeliveryPartner.objects.select_related("user", "home_store")
    if lock:
        partners = DeliveryPartner.objects.select_for_update()
    return partners.get(user=request.user)


class DeliveryMeView(APIView):
    permission_classes = [IsDeliveryPartner]

    @extend_schema(responses=DeliveryPartnerSerializer)
    def get(self, request):
        return Response(DeliveryPartnerSerializer(_me(request)).data)

    @extend_schema(request=AvailabilitySerializer, responses=DeliveryPartnerSerializer)
    @transaction.atomic
    def patch(self, request):
        serializer = AvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        partner = _me(request, lock=True)
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


class DeliveryLocationView(APIView):
    """The rider's phone reports where it is (used to offer nearby jobs). Only the latest
    position is kept."""

    permission_classes = [IsDeliveryPartner]

    @extend_schema(request=LocationPingSerializer, responses={204: None})
    def post(self, request):
        serializer = LocationPingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        partner = _me(request)
        partner.current_latitude = serializer.validated_data["latitude"]
        partner.current_longitude = serializer.validated_data["longitude"]
        partner.last_location_at = timezone.now()
        partner.save(update_fields=["current_latitude", "current_longitude", "last_location_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("scope", str, enum=["active", "history"]),
            OpenApiParameter("kind", str, enum=["delivery", "return_pickup"]),
        ]
    )
)
class AssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    """The rider's jobs and the steps they can take on them."""

    permission_classes = [IsDeliveryPartner]
    serializer_class = AssignmentSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryAssignment.objects.none()
        qs = assignment_queryset().filter(partner__user=self.request.user)
        scope = self.request.query_params.get("scope")
        if scope == "active":
            qs = qs.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).order_by("assigned_at")
        elif scope == "history":
            qs = qs.exclude(status__in=DeliveryAssignment.ACTIVE_STATUSES)
        if kind := self.request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
        return qs

    def _result(self, assignment: DeliveryAssignment) -> Response:
        fresh = assignment_queryset().get(pk=assignment.pk)
        return Response(AssignmentSerializer(fresh, context={"request": self.request}).data)

    def _input(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer

    @extend_schema(request=None, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._result(workflow.accept(self.get_object().pk, rider=request.user))

    @extend_schema(request=RejectSerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        job = self.get_object()
        data = self._input(RejectSerializer).validated_data
        return self._result(workflow.reject(job.pk, rider=request.user, reason=data["reason"]))

    @extend_schema(request=StepSerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def pickup(self, request, pk=None):
        job = self.get_object()
        position = self._input(StepSerializer).position()
        return self._result(workflow.pickup(job.pk, rider=request.user, position=position))

    @extend_schema(request=StepSerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        job = self.get_object()
        position = self._input(StepSerializer).position()
        return self._result(workflow.start_delivery(job.pk, rider=request.user, position=position))

    @extend_schema(request=CompleteDeliverySerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        job = self.get_object()
        serializer = self._input(CompleteDeliverySerializer)
        data = serializer.validated_data
        assignment = workflow.complete_delivery(
            job.pk,
            rider=request.user,
            code=data["otp"],
            cod=serializer.cod(),
            received_by=data["received_by"],
            notes=data.get("notes"),
            position=serializer.position(),
        )
        return self._result(assignment)

    @extend_schema(request=FailDeliverySerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        job = self.get_object()
        serializer = self._input(FailDeliverySerializer)
        data = serializer.validated_data
        assignment = workflow.fail_delivery(
            job.pk,
            rider=request.user,
            reason_code=data["reason"],
            note=data["note"],
            position=serializer.position(),
        )
        return self._result(assignment)

    @extend_schema(request=NotesSerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["patch"])
    def notes(self, request, pk=None):
        job = self.get_object()
        data = self._input(NotesSerializer).validated_data
        return self._result(workflow.update_notes(job.pk, rider=request.user, notes=data["notes"]))

    @extend_schema(
        methods=["post"],
        request={"multipart/form-data": ProofUploadSerializer},
        responses=AssignmentSerializer,
    )
    @extend_schema(methods=["get"], responses={(200, "image/jpeg"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get", "post"])
    def proof(self, request, pk=None):
        """POST: upload the photo (multipart field `photo`). GET: the rider's own photo."""
        assignment = self.get_object()
        if request.method == "GET":
            return proof_response(assignment)
        data = self._input(ProofUploadSerializer).validated_data
        return self._result(
            workflow.upload_proof(
                assignment.pk, rider=request.user, photo=data["photo"], received_by=data["received_by"]
            )
        )


class EarningsView(APIView):
    permission_classes = [IsDeliveryPartner]

    @extend_schema(responses=EarningsSerializer)
    def get(self, request):
        now = timezone.now()
        # Explicit range instead of `__date`: MySQL needs timezone tables for tz-aware __date lookups,
        # which shared hosts often don't load.
        start_of_today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        delivered = Q(status=DeliveryAssignment.Status.DELIVERED)
        today = delivered & Q(delivered_at__gte=start_of_today)
        mine = DeliveryAssignment.objects.filter(partner__user=request.user)
        agg = mine.aggregate(
            delivered_count=Count("id", filter=delivered),
            today_count=Count("id", filter=today),
            failed_count=Count("id", filter=Q(status=DeliveryAssignment.Status.FAILED)),
            total=Sum("earning_amount"),
            today=Sum("earning_amount", filter=Q(delivered_at__gte=start_of_today) | Q(failed_at__gte=start_of_today)),
            week=Sum(
                "earning_amount",
                filter=Q(delivered_at__gte=now - timedelta(days=7)) | Q(failed_at__gte=now - timedelta(days=7)),
            ),
        )
        zero = Decimal("0.00")
        partner = _me(request)
        return Response(
            EarningsSerializer(
                {
                    "delivered_count": agg["delivered_count"],
                    "total_earnings": agg["total"] or zero,
                    "today_earnings": agg["today"] or zero,
                    "last_7_days_earnings": agg["week"] or zero,
                    "today_delivered_count": agg["today_count"],
                    "failed_count": agg["failed_count"],
                    "cash_in_hand": cash_in_hand(partner),
                    "cash_deliveries_pending_handover": cash_not_handed_over(mine).count(),
                }
            ).data
        )
