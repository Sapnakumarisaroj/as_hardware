"""Quote requests (customers) and quotations (staff).

Customers: /api/quotes/ — list, request (from chosen lines or the cart), view, accept, close.
Staff: /api/admin/quotes/ — admins send/revise quotations and reject; store managers can read.
Ordering an accepted quotation goes through the normal checkout (`quote_id` on
/api/checkout/preview/ and /api/orders/).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsAdminOrStaffReadOnly

from . import services
from .models import Quote
from .serializers import (
    AdminQuoteSerializer,
    CloseQuoteSerializer,
    QuoteSerializer,
    RejectQuoteSerializer,
    RequestQuoteSerializer,
    SendQuotationSerializer,
)


def _with_items(qs):
    return qs.select_related("order", "user").prefetch_related("items__variant__product")


class QuoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Quote.objects.none()
        return _with_items(Quote.objects.filter(user=self.request.user))

    def _fresh(self, quote_id: int, code=status.HTTP_200_OK) -> Response:
        return Response(QuoteSerializer(self.get_queryset().get(pk=quote_id)).data, status=code)

    @extend_schema(request=RequestQuoteSerializer, responses={201: QuoteSerializer})
    def create(self, request):
        serializer = RequestQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lines = [services.RequestedLine(i["variant_id"], i["quantity"], i["note"]) for i in data.get("items") or []]
        if data["from_cart"]:
            from apps.carts.models import CartItem

            lines += [
                services.RequestedLine(item.variant_id, item.quantity)
                for item in CartItem.objects.filter(cart__user=request.user).order_by("created_at", "id")
            ]
        quote = services.request_quote(request.user, lines, note=data["note"], address_id=data.get("address_id"))
        return self._fresh(quote.pk, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=QuoteSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        quote = services.accept_quote(request.user, int(pk))
        return self._fresh(quote.pk)

    @extend_schema(request=CloseQuoteSerializer, responses=QuoteSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        serializer = CloseQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = services.close_by_customer(request.user, int(pk), serializer.validated_data["reason"])
        return self._fresh(quote.pk)


class AdminQuoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = AdminQuoteSerializer
    permission_classes = [IsAdminOrStaffReadOnly]

    def get_queryset(self):
        qs = _with_items(Quote.objects.all())
        if status_filter := self.request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        if search := (self.request.query_params.get("q") or "").strip():
            qs = qs.filter(number__icontains=search) | qs.filter(user__email__icontains=search)
        return qs

    def _fresh(self, quote_id: int) -> Response:
        return Response(AdminQuoteSerializer(_with_items(Quote.objects.all()).get(pk=quote_id)).data)

    @extend_schema(request=SendQuotationSerializer, responses=AdminQuoteSerializer)
    @action(detail=True, methods=["post"])
    def quotation(self, request, pk=None):
        serializer = SendQuotationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        quote = services.send_quotation(
            int(pk),
            actor=request.user,
            prices={line["item_id"]: line["unit_price"] for line in data["lines"]},
            valid_days=data["valid_days"],
            shop_note=data["shop_note"],
            request=request,
        )
        return self._fresh(quote.pk)

    @extend_schema(request=RejectQuoteSerializer, responses=AdminQuoteSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        serializer = RejectQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = services.reject_quote(
            int(pk), actor=request.user, reason=serializer.validated_data["reason"], request=request
        )
        return self._fresh(quote.pk)
