from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.catalog.selectors import annotate_listing
from apps.offers.services import coupon_discount, get_valid_coupon
from apps.orders.pricing import calculate_totals

from . import services
from .models import WishlistItem
from .serializers import (
    AddCartItemSerializer,
    AddWishlistItemSerializer,
    CartSerializer,
    CouponPreviewRequestSerializer,
    CouponPreviewSerializer,
    UpdateCartItemSerializer,
    WishlistItemSerializer,
)


def _cart_response(request, status_code=status.HTTP_200_OK):
    data = CartSerializer(services.summarize_cart(request.user), context={"request": request}).data
    return Response(data, status=status_code)


class CartView(APIView):
    @extend_schema(responses=CartSerializer)
    def get(self, request):
        return _cart_response(request)

    @extend_schema(responses=CartSerializer)
    def delete(self, request):
        services.clear_cart(request.user)
        return _cart_response(request)


class CartItemsView(APIView):
    @extend_schema(request=AddCartItemSerializer, responses={201: CartSerializer})
    def post(self, request):
        serializer = AddCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_item(request.user, **serializer.validated_data)
        return _cart_response(request, status.HTTP_201_CREATED)


class CartItemDetailView(APIView):
    @extend_schema(request=UpdateCartItemSerializer, responses=CartSerializer)
    def patch(self, request, item_id: int):
        serializer = UpdateCartItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_item_quantity(request.user, item_id, serializer.validated_data["quantity"])
        return _cart_response(request)

    @extend_schema(responses=CartSerializer)
    def delete(self, request, item_id: int):
        services.remove_item(request.user, item_id)
        return _cart_response(request)


class CouponPreviewView(APIView):
    """Validate a coupon against the current cart and show the resulting totals. Nothing is reserved."""

    @extend_schema(request=CouponPreviewRequestSerializer, responses=CouponPreviewSerializer)
    def post(self, request):
        serializer = CouponPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary = services.summarize_cart(request.user)
        coupon = get_valid_coupon(serializer.validated_data["code"], request.user)
        discount = coupon_discount(coupon, summary.priced_lines, summary.totals.subtotal)
        totals = calculate_totals(summary.priced_lines, discount)
        payload = {"code": coupon.code, "description": coupon.description, "discount": discount, "totals": totals}
        return Response(CouponPreviewSerializer(payload).data)


class WishlistView(APIView):
    @extend_schema(responses=WishlistItemSerializer(many=True))
    def get(self, request):
        wishlist = services.get_wishlist(request.user)
        items = list(WishlistItem.objects.filter(wishlist=wishlist).order_by("-created_at"))
        products = {
            p.pk: p
            for p in annotate_listing(
                Product.objects.select_related("brand", "category", "subcategory").prefetch_related("images")
            ).filter(pk__in=[i.product_id for i in items])
        }
        rows = [
            {"product": products[i.product_id], "created_at": i.created_at} for i in items if i.product_id in products
        ]
        return Response(WishlistItemSerializer(rows, many=True, context={"request": request}).data)

    @extend_schema(request=AddWishlistItemSerializer, responses={201: None})
    def post(self, request):
        serializer = AddWishlistItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_to_wishlist(request.user, serializer.validated_data["product_id"])
        return Response({"product_id": serializer.validated_data["product_id"]}, status=status.HTTP_201_CREATED)


class WishlistItemView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request, product_id: int):
        services.remove_from_wishlist(request.user, product_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
