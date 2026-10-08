"""Phase 9 delivery APIs: zones, serviceability, delivery estimates, store availability, and the
staff side of rider assignment. Every estimate comes from the fulfilment engine; nothing here
promises a fixed time."""

from django.conf import settings
from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.carts.services import summarize_cart
from apps.catalog.models import ProductVariant
from apps.catalog.selectors import stock_status
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError
from apps.core.permissions import IsStaffRole, managed_store_ids
from apps.inventory.models import Inventory
from apps.orders.checkout import quote_from_plan
from apps.orders.models import OrderShipment, ShipmentStatus
from apps.orders.pricing import line_from_variant, price_lines
from apps.orders.serializers import DeliveryQuoteSerializer

from . import workflow
from .assignment import (
    ASSIGNABLE_ORDER_STATUSES,
    ASSIGNABLE_SHIPMENT_STATUSES,
    assign_shipment,
    eligible_partners,
    partners_with_load,
    reassign_shipment,
    unassign_shipment,
)
from .cod import cash_by_partner
from .eta import estimate, straight_line_km
from .fulfillment import covering_candidates, fulfilment_stores, plan_fulfillment, zone_covers
from .locations import resolve_location
from .models import DeliveryAssignment, DeliveryPartner, DeliveryZone
from .serializers import (
    AssignShipmentSerializer,
    CodCollectionSerializer,
    CompleteWithoutOtpSerializer,
    EligiblePartnerSerializer,
    HandoverSerializer,
    LocationQuerySerializer,
    PartnerAvailabilitySerializer,
    ProductEstimateQuerySerializer,
    ReassignSerializer,
    ServiceabilitySerializer,
    StaffShipmentDetailSerializer,
    StaffShipmentSerializer,
    StoreAvailabilitySerializer,
    UnassignSerializer,
    ZoneSerializer,
)
from .views import proof_response

KIND = DeliveryAssignment.Kind

LOCATION_PARAMS = [
    OpenApiParameter("postal_code", str, description="6-digit PIN code"),
    OpenApiParameter("latitude", float),
    OpenApiParameter("longitude", float),
    OpenApiParameter("address_id", int, description="A saved address (signed-in customers only)"),
]


def _location(request, data):
    if address_id := data.get("address_id"):
        if not request.user.is_authenticated:
            raise NotAuthenticated("Sign in to use a saved address.")
        address = Address.objects.filter(pk=address_id, user=request.user).first()
        if address is None:
            raise NotFoundError("Address not found.")
        return resolve_location(address=address)
    return resolve_location(
        postal_code=data.get("postal_code", ""), latitude=data.get("latitude"), longitude=data.get("longitude")
    )


class DeliveryZonesView(APIView):
    """Active delivery zones with their fee rules and fast-delivery settings (public)."""

    permission_classes = [AllowAny]

    @extend_schema(responses=ZoneSerializer(many=True))
    def get(self, request):
        zones = DeliveryZone.objects.filter(is_active=True, store__in=fulfilment_stores()).select_related("store")
        return Response(ZoneSerializer(zones, many=True).data)


class DeliveryPromiseView(APIView):
    """The shop-wide fast-delivery promise for the storefront badge ("60 Mins"). Only a service
    indicator: whether an order is fast is decided per PIN, zone, stock, store, rider and travel time
    (eta.py), and a zone may promise less than this."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer("DeliveryPromise", {"fast_delivery_max_minutes": serializers.IntegerField()})
    )
    def get(self, request):
        return Response({"fast_delivery_max_minutes": settings.FAST_DELIVERY_MAX_MINUTES})


class ServiceabilityView(APIView):
    """Do we deliver here, and roughly how fast? Indicative (for an item in stock at the nearest store)."""

    permission_classes = [AllowAny]

    @extend_schema(parameters=LOCATION_PARAMS, responses=ServiceabilitySerializer)
    def get(self, request):
        query = LocationQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        location = _location(request, query.validated_data)
        estimates = [estimate(store, zone, location, line_count=1) for store, zone in covering_candidates(location)]
        estimates.sort(key=lambda e: e.sort_key())
        best = estimates[0] if estimates else None
        where = f"PIN {location.postal_code}" if location.postal_code else "this location"
        payload = {
            "serviceable": best is not None,
            "postal_code": location.postal_code,
            "location_precision": location.precision,
            "fast_delivery_available": bool(best and best.fast_available),
            "label": best.label if best else "",
            "fast_unavailable_reason": best.fast_unavailable_reason if best else "",
            "message": (
                ("⚡ Fast delivery available" if best.fast_available else "🚚 Standard delivery") + f" · {best.label}"
                if best
                else f"We don't deliver to {where} yet."
            ),
            "stores": [
                {
                    "name": e.store.name,
                    "area": e.store.area,
                    "distance_km": round(e.distance_km, 1) if e.distance_km is not None else None,
                    "fast_available": e.fast_available,
                    "eta_minutes": e.eta_minutes,
                    "label": e.label,
                }
                for e in estimates
            ],
        }
        return Response(ServiceabilitySerializer(payload).data)


class ProductDeliveryEstimateView(APIView):
    """Delivery estimate for one product variant and quantity to a location (product page)."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("variant_id", int, required=True),
            OpenApiParameter("quantity", int),
            *LOCATION_PARAMS,
        ],
        responses=DeliveryQuoteSerializer,
    )
    def get(self, request):
        query = ProductEstimateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        variant = (
            ProductVariant.objects.select_related("product")
            .filter(pk=data["variant_id"], is_active=True, product__is_deleted=False)
            .first()
        )
        if variant is None or not variant.product.is_purchasable:
            raise NotFoundError("Product not found.")
        plan = plan_fulfillment({variant.pk: data["quantity"]}, _location(request, data))
        fee_rule = plan.fee_rule if plan.deliverable else None
        user = request.user if request.user.is_authenticated else None
        # The same pricing engine as the cart (bulk tier, offers, free-delivery rules for this zone).
        totals = price_lines([line_from_variant(variant, data["quantity"])], fee_rule=fee_rule, user=user).totals
        quote = quote_from_plan(plan, totals, fee_rule)
        return Response(DeliveryQuoteSerializer(quote).data)


class CartDeliveryEstimateView(APIView):
    """Delivery estimate for the signed-in customer's current cart (cart page)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=LOCATION_PARAMS, responses=DeliveryQuoteSerializer)
    def get(self, request):
        query = LocationQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        location = _location(request, query.validated_data)
        cart = summarize_cart(request.user)
        requirements = {line.item.variant_id: line.item.quantity for line in cart.lines if line.in_stock}
        plan = plan_fulfillment(requirements, location)
        fee_rule = plan.fee_rule if plan.deliverable else None
        totals = price_lines(cart.priced_lines, fee_rule=fee_rule, user=request.user).totals
        quote = quote_from_plan(plan, totals, fee_rule)
        return Response(DeliveryQuoteSerializer(quote).data)


class StoreAvailabilityView(APIView):
    """Which stores hold a product (status only, never quantities) and whether they deliver to you."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("variant_id", int, required=True), *LOCATION_PARAMS],
        responses=StoreAvailabilitySerializer(many=True),
    )
    def get(self, request):
        try:
            variant_id = int(request.query_params.get("variant_id", ""))
        except ValueError:
            raise NotFoundError("Product not found.") from None
        location = None
        if any(k in request.query_params for k in ("address_id", "postal_code", "latitude")):
            query = LocationQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            location = _location(request, query.validated_data)
        stores = list(
            fulfilment_stores().prefetch_related(
                Prefetch("delivery_zones", DeliveryZone.objects.filter(is_active=True))
            )
        )
        stock = dict(
            Inventory.objects.filter(variant_id=variant_id, is_active=True, store__in=stores).values_list(
                "store_id", "available_quantity"
            )
        )
        rows = []
        for store in stores:
            covers = None
            distance = None
            if location is not None:
                covers = any(zone_covers(z, store, location) for z in store.delivery_zones.all())
                d = straight_line_km(store, location)
                distance = round(d, 1) if d is not None else None
            rows.append(
                {
                    "store_name": store.name,
                    "store_area": store.area,
                    "city": store.city,
                    "kind": store.kind,
                    "stock_status": stock_status(stock.get(store.pk, 0)),
                    "delivers_to_location": covers,
                    "distance_km": distance,
                }
            )
        rows.sort(key=lambda r: (r["delivers_to_location"] is False, r["distance_km"] or 1e9, r["store_name"]))
        return Response(StoreAvailabilitySerializer(rows, many=True).data)


SHIPMENT_SCOPES = ["waiting", "active", "failed", "delivered", "all"]


def _partner(partner_id: int) -> DeliveryPartner:
    partner = DeliveryPartner.objects.filter(pk=partner_id).first()
    if partner is None:
        raise NotFoundError("Delivery partner not found.")
    return partner


class ShipmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Staff: shipments of their stores. Assign, reassign or unassign riders, follow the delivery
    status, see the delivery history and the proof of delivery."""

    permission_classes = [IsStaffRole]
    serializer_class = StaffShipmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return OrderShipment.objects.none()
        qs = OrderShipment.objects.select_related("order", "store").prefetch_related(
            "items",
            Prefetch(
                "assignments",
                DeliveryAssignment.objects.select_related("partner__user").prefetch_related("status_history"),
            ),
        )
        store_ids = managed_store_ids(self.request.user)
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)
        if self.action != "list":
            return qs
        scope = self.request.query_params.get("scope", "waiting")
        active = DeliveryAssignment.objects.filter(kind=KIND.DELIVERY, status__in=DeliveryAssignment.ACTIVE_STATUSES)
        if scope == "waiting":
            qs = qs.filter(
                order__status__in=ASSIGNABLE_ORDER_STATUSES, status__in=ASSIGNABLE_SHIPMENT_STATUSES
            ).exclude(pk__in=active.values("shipment_id"))
        elif scope == "active":
            qs = qs.filter(pk__in=active.values("shipment_id"))
        elif scope == "failed":
            qs = qs.filter(status=ShipmentStatus.FAILED)
        elif scope == "delivered":
            qs = qs.filter(status=ShipmentStatus.DELIVERED).order_by("-delivered_at")
        if status_filter := self.request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        return qs if scope == "delivered" else qs.order_by("estimated_ready_at", "id")

    def get_serializer_class(self):
        return StaffShipmentDetailSerializer if self.action == "retrieve" else StaffShipmentSerializer

    @extend_schema(
        parameters=[OpenApiParameter("scope", str, enum=SHIPMENT_SCOPES), OpenApiParameter("status", str)],
        responses=StaffShipmentSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _detail(self, shipment, status_code=status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=shipment.pk)
        return Response(StaffShipmentDetailSerializer(fresh).data, status=status_code)

    @extend_schema(responses=EligiblePartnerSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="eligible-partners")
    def eligible(self, request, pk=None):
        shipment = self._shipment(pk)
        return Response(EligiblePartnerSerializer(eligible_partners(shipment), many=True).data)

    @extend_schema(request=AssignShipmentSerializer, responses={201: None})
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Also sends a shipment out again after a failed delivery."""
        shipment = self._shipment(pk)
        body = AssignShipmentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        partner = _partner(body.validated_data["partner_id"])
        assignment = assign_shipment(shipment, partner, actor=request.user)
        return Response(
            {"assignment_id": assignment.pk, "order_status": assignment.order.status, "partner_id": partner.pk},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=ReassignSerializer, responses={201: StaffShipmentDetailSerializer})
    @action(detail=True, methods=["post"])
    def reassign(self, request, pk=None):
        shipment = self._shipment(pk)
        body = ReassignSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        partner = _partner(body.validated_data["partner_id"])
        reassign_shipment(shipment, partner, actor=request.user, reason=body.validated_data["reason"])
        return self._detail(shipment, status.HTTP_201_CREATED)

    @extend_schema(request=UnassignSerializer, responses=StaffShipmentDetailSerializer)
    @action(detail=True, methods=["post"])
    def unassign(self, request, pk=None):
        shipment = self._shipment(pk)
        body = UnassignSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        unassign_shipment(shipment, actor=request.user, reason=body.validated_data["reason"])
        return self._detail(shipment)

    @extend_schema(request=CompleteWithoutOtpSerializer, responses=StaffShipmentDetailSerializer)
    @action(detail=True, methods=["post"], url_path="complete-without-otp")
    def complete_without_otp(self, request, pk=None):
        """The customer could not show the delivery code. Needs a note; audit-logged."""
        shipment = self._shipment(pk)
        body = CompleteWithoutOtpSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        job = shipment.assignments.filter(kind=KIND.DELIVERY, status=DeliveryAssignment.Status.OUT_FOR_DELIVERY).first()
        if job is None:
            raise ConflictError("This shipment is not out for delivery with a partner.", code="invalid_delivery_state")
        workflow.complete_without_otp(
            job.pk,
            actor=request.user,
            note=data["note"],
            cod={
                "collected": data["cod_collected"],
                "amount": data.get("cod_amount"),
                "method": data.get("cod_method"),
                "reference": data["cod_reference"],
            },
        )
        return self._detail(shipment)

    @extend_schema(responses={(200, "image/jpeg"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def proof(self, request, pk=None):
        shipment = self._shipment(pk)
        job = (
            shipment.assignments.filter(kind=KIND.DELIVERY)
            .exclude(proof_image="")
            .order_by("-proof_uploaded_at")
            .first()
        )
        if job is None:
            raise NotFoundError("No photo was uploaded for this delivery.")
        record_audit(action="delivery.proof_viewed", actor=request.user, target=job, request=request)
        return proof_response(job)

    def _shipment(self, pk) -> OrderShipment:
        shipment = OrderShipment.objects.select_related("store", "order").filter(pk=pk).first()
        allowed = managed_store_ids(self.request.user)
        if shipment is None or (allowed is not None and shipment.store_id not in allowed):
            raise NotFoundError("Shipment not found.")
        return shipment


def _staff_scoped_assignments(user):
    """Jobs at the stores this staff member runs (admins: all)."""
    qs = DeliveryAssignment.objects.select_related("order", "shipment__store", "partner__user", "cod_handed_over_to")
    store_ids = managed_store_ids(user)
    return qs if store_ids is None else qs.filter(shipment__store_id__in=store_ids)


class PartnerAvailabilityView(APIView):
    """Staff: the riders of their stores, who is online, their load and the cash they carry."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=["offline", "available", "busy"])],
        responses=PartnerAvailabilitySerializer(many=True),
    )
    def get(self, request):
        partners = partners_with_load().order_by("home_store__name", "user__full_name")
        store_ids = managed_store_ids(request.user)
        if store_ids is not None:
            partners = partners.filter(home_store_id__in=store_ids)
        if wanted := request.query_params.get("status"):
            partners = partners.filter(status=wanted)
        partners = list(partners)
        cash = cash_by_partner([p.pk for p in partners])
        return Response(PartnerAvailabilitySerializer(partners, many=True, context={"cash": cash}).data)


class CodCollectionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Staff: cash-on-delivery money collected by riders, and its handover to the store."""

    permission_classes = [IsStaffRole]
    serializer_class = CodCollectionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryAssignment.objects.none()
        qs = _staff_scoped_assignments(self.request.user).filter(cod_collected_at__isnull=False)
        handed = self.request.query_params.get("handed_over")
        if handed in ("true", "false"):
            qs = qs.filter(cod_handed_over_at__isnull=handed == "false")
        if partner_id := self.request.query_params.get("partner"):
            qs = qs.filter(partner_id=partner_id) if partner_id.isdigit() else qs.none()
        return qs.order_by("-cod_collected_at")

    @extend_schema(
        parameters=[
            OpenApiParameter("handed_over", str, enum=["true", "false"]),
            OpenApiParameter("partner", int, description="Delivery partner id"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=HandoverSerializer, responses=CodCollectionSerializer)
    @action(detail=True, methods=["post"])
    def handover(self, request, pk=None):
        """The store received the cash of this delivery from the rider."""
        job = _staff_scoped_assignments(request.user).filter(pk=pk).first()
        if job is None:
            raise NotFoundError("Delivery not found.")
        body = HandoverSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        workflow.hand_over_cash(job.pk, actor=request.user, note=body.validated_data["note"])
        return Response(CodCollectionSerializer(_staff_scoped_assignments(request.user).get(pk=job.pk)).data)
