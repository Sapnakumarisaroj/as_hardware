"""Dashboard session, summary and analytics."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStaffRole, is_admin, managed_store_ids
from apps.stores.models import Store

from . import metrics
from .scope import date_range, store_ids_for

# What each role may open. The dashboard builds its menu from this list; every API checks the
# role again, so hiding a menu entry is a convenience, not the protection.
ADMIN_SECTIONS = [
    "dashboard", "orders", "products", "categories", "brands", "inventory", "stores", "warehouses",
    "delivery", "offers", "coupons", "customers", "returns", "refunds", "support", "analytics", "search",
    "options", "collections", "free-delivery", "payment-settings", "loyalty", "bundles", "recommendations",
]  # fmt: skip
MANAGER_SECTIONS = [
    "dashboard", "orders", "inventory", "stores", "delivery", "returns", "refunds", "support", "analytics",
]  # fmt: skip
STORE_PARAM = OpenApiParameter("store", int, description="One store (administrators: any; managers: their own)")


class SessionView(APIView):
    """Who is using the dashboard, which sections they may open and which stores they work with."""

    permission_classes = [IsStaffRole]

    @extend_schema(responses={200: None})
    def get(self, request):
        user = request.user
        admin = is_admin(user)
        stores = Store.objects.order_by("name")
        allowed = managed_store_ids(user)
        if allowed is not None:
            stores = stores.filter(pk__in=allowed)
        return Response(
            {
                "user": {"id": user.pk, "full_name": user.full_name, "email": user.email, "role": user.role},
                "is_admin": admin,
                "sections": ADMIN_SECTIONS if admin else MANAGER_SECTIONS,
                "stores": [{"id": s.pk, "name": s.name, "code": s.code, "kind": s.kind} for s in stores],
                "can": {
                    "manage_catalog": admin,
                    "manage_stores": admin,
                    "manage_offers": admin,
                    "manage_customers": admin,
                    "manage_riders": admin,
                    "adjust_stock": True,
                    "handle_orders": True,
                    "handle_returns": True,
                },
            }
        )


class SummaryView(APIView):
    """Live numbers for the dashboard home. Managers get the numbers of their stores."""

    permission_classes = [IsStaffRole]

    @extend_schema(parameters=[STORE_PARAM], responses={200: None})
    def get(self, request):
        admin = is_admin(request.user)
        store_ids = store_ids_for(request)
        shop_wide = admin and not request.query_params.get("store")
        return Response(metrics.dashboard_summary(store_ids, is_admin=shop_wide))


class AnalyticsView(APIView):
    permission_classes = [IsStaffRole]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="First day (YYYY-MM-DD). Default: 30 days ago"),
            OpenApiParameter("to", str, description="Last day (YYYY-MM-DD). Default: today"),
            OpenApiParameter("group_by", str, enum=["day", "week", "month"]),
            STORE_PARAM,
        ],
        responses={200: None},
    )
    def get(self, request):
        first, last, start, end = date_range(request)
        period = request.query_params.get("group_by")
        if period not in ("day", "week", "month"):
            days = (last - first).days + 1
            period = "day" if days <= 45 else "week" if days <= 180 else "month"
        return Response(metrics.analytics(store_ids_for(request), first, last, start, end, period))
