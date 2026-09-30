from django.urls import path
from rest_framework.routers import SimpleRouter

from .catalog import AdminBrandViewSet, AdminCategoryViewSet, AdminProductViewSet, VariantSearchView
from .offers import AdminCouponViewSet, AdminOfferViewSet
from .orders import AdminOrderViewSet
from .people import AdminCustomerViewSet, AdminJobViewSet, AdminRiderViewSet, AdminSupportViewSet
from .stores import AdminPinCodeViewSet, AdminStoreViewSet, AdminZoneViewSet
from .views import AnalyticsView, SessionView, SummaryView

router = SimpleRouter()
router.register("admin/orders", AdminOrderViewSet, basename="admin-order")
router.register("admin/products", AdminProductViewSet, basename="admin-product")
router.register("admin/variants", VariantSearchView, basename="admin-variant")
router.register("admin/categories", AdminCategoryViewSet, basename="admin-category")
router.register("admin/brands", AdminBrandViewSet, basename="admin-brand")
router.register("admin/stores", AdminStoreViewSet, basename="admin-store")
router.register("admin/zones", AdminZoneViewSet, basename="admin-zone")
router.register("admin/pincodes", AdminPinCodeViewSet, basename="admin-pincode")
router.register("admin/offers", AdminOfferViewSet, basename="admin-offer")
router.register("admin/coupons", AdminCouponViewSet, basename="admin-coupon")
router.register("admin/customers", AdminCustomerViewSet, basename="admin-customer")
router.register("admin/riders", AdminRiderViewSet, basename="admin-rider")
router.register("admin/jobs", AdminJobViewSet, basename="admin-job")
router.register("admin/support", AdminSupportViewSet, basename="admin-support")

urlpatterns = [
    path("admin/session/", SessionView.as_view(), name="admin-session"),
    path("admin/summary/", SummaryView.as_view(), name="admin-summary"),
    path("admin/analytics/", AnalyticsView.as_view(), name="admin-analytics"),
    *router.urls,
]
