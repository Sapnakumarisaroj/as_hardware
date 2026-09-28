"""Phase 9 delivery APIs: zones, serviceability, delivery estimates, store availability, and the
staff side of rider assignment. Every estimate comes from the fulfilment engine; nothing here
promises a fixed time."""

from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.carts.services import summarize_cart
from apps.catalog.models import ProductVariant
from apps.catalog.selectors import stock_status
from apps.core.exceptions import NotFoundError
from apps.core.money import q
from apps.core.permissions import IsStaffRole, managed_store_ids
from apps.inventory.models import Inventory
from apps.orders.checkout import quote_from_plan
from apps.orders.models import OrderShipment
from apps.orders.serializers import DeliveryQuoteSerializer

from .assignment import ASSIGNABLE_ORDER_STATUSES, assign_shipment, eligible_partners
from .eta import estimate, straight_line_km
from .fulfillment import covering_candidates, fulfilment_stores, plan_fulfillment, zone_covers
from .locations import resolve_location
from .models import DeliveryAssignment, DeliveryPartner, DeliveryZone
from .serializers import (
    AssignShipmentSerializer,
    EligiblePartnerSerializer,
    LocationQuerySerializer,
    ProductEstimateQuerySerializer,
    ServiceabilitySerializer,
    StaffShipmentSerializer,
    StoreAvailabilitySerializer,
    ZoneSerializer,
)

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
        quote = quote_from_plan(plan, q(variant.price * data["quantity"]), plan.fee_rule if plan.deliverable else None)
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
        amount = cart.totals.subtotal - cart.totals.discount_total
        quote = quote_from_plan(plan, amount, plan.fee_rule if plan.deliverable else None)
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


class ShipmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Staff: shipments waiting for a rider at their stores; see eligible riders; assign one."""

    permission_classes = [IsStaffRole]
    serializer_class = StaffShipmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return OrderShipment.objects.none()
        qs = OrderShipment.objects.select_related("order", "store").prefetch_related(
            Prefetch("assignments", DeliveryAssignment.objects.select_related("partner__user"))
        )
        store_ids = managed_store_ids(self.request.user)
        if store_ids is not None:
            qs = qs.filter(store_id__in=store_ids)
        if self.request.query_params.get("scope", "waiting") == "waiting":
            qs = qs.filter(order__status__in=ASSIGNABLE_ORDER_STATUSES).exclude(
                assignments__status__in=DeliveryAssignment.ACTIVE_STATUSES
            )
        return qs.order_by("estimated_ready_at", "id")

    @extend_schema(
        parameters=[OpenApiParameter("scope", str, enum=["waiting", "all"])],
        responses=StaffShipmentSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=EligiblePartnerSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="eligible-partners")
    def eligible(self, request, pk=None):
        shipment = self._shipment(pk)
        return Response(EligiblePartnerSerializer(eligible_partners(shipment), many=True).data)

    @extend_schema(request=AssignShipmentSerializer, responses={201: None})
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        shipment = self._shipment(pk)
        body = AssignShipmentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        partner = DeliveryPartner.objects.filter(pk=body.validated_data["partner_id"]).first()
        if partner is None:
            raise NotFoundError("Delivery partner not found.")
        assignment = assign_shipment(shipment, partner, actor=request.user)
        return Response(
            {"assignment_id": assignment.pk, "order_status": assignment.order.status, "partner_id": partner.pk},
            status=status.HTTP_201_CREATED,
        )

    def _shipment(self, pk) -> OrderShipment:
        shipment = OrderShipment.objects.select_related("store", "order").filter(pk=pk).first()
        allowed = managed_store_ids(self.request.user)
        if shipment is None or (allowed is not None and shipment.store_id not in allowed):
            raise NotFoundError("Shipment not found.")
        return shipment
