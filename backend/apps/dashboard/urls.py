from django.urls import path
from rest_framework.routers import SimpleRouter

from .catalog import (
    AdminBrandViewSet,
    AdminCategoryViewSet,
    AdminProductViewSet,
    CatalogExportView,
    CatalogImportView,
    CatalogTemplateView,
    VariantSearchView,
)
from .commerce import (
    AdminCollectionViewSet,
    AdminFreeDeliveryRuleViewSet,
    AdminOptionTypeViewSet,
    PaymentSettingsView,
)
from .offers import AdminCouponViewSet, AdminOfferViewSet
from .orders import AdminOrderViewSet
from .people import AdminCustomerViewSet, AdminJobViewSet, AdminRiderViewSet, AdminSupportViewSet
from .search_index import SearchExplainView, SearchIndexProductView, SearchIndexRebuildView, SearchIndexView
from .stores import AdminPinCodeViewSet, AdminServiceAreaViewSet, AdminStoreViewSet, AdminZoneViewSet
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
router.register("admin/service-areas", AdminServiceAreaViewSet, basename="admin-service-area")
router.register("admin/offers", AdminOfferViewSet, basename="admin-offer")
router.register("admin/coupons", AdminCouponViewSet, basename="admin-coupon")
router.register("admin/customers", AdminCustomerViewSet, basename="admin-customer")
router.register("admin/riders", AdminRiderViewSet, basename="admin-rider")
router.register("admin/jobs", AdminJobViewSet, basename="admin-job")
router.register("admin/support", AdminSupportViewSet, basename="admin-support")
router.register("admin/option-types", AdminOptionTypeViewSet, basename="admin-option-type")
router.register("admin/collections", AdminCollectionViewSet, basename="admin-collection")
router.register("admin/free-delivery-rules", AdminFreeDeliveryRuleViewSet, basename="admin-free-delivery-rule")

urlpatterns = [
    path("admin/session/", SessionView.as_view(), name="admin-session"),
    path("admin/summary/", SummaryView.as_view(), name="admin-summary"),
    path("admin/analytics/", AnalyticsView.as_view(), name="admin-analytics"),
    path("admin/search/index/", SearchIndexView.as_view(), name="admin-search-index"),
    path("admin/search/index/rebuild/", SearchIndexRebuildView.as_view(), name="admin-search-rebuild"),
    path("admin/search/index/products/<int:pk>/", SearchIndexProductView.as_view(), name="admin-search-product"),
    path("admin/search/explain/", SearchExplainView.as_view(), name="admin-search-explain"),
    path("admin/catalog/import/", CatalogImportView.as_view(), name="admin-catalog-import"),
    path("admin/catalog/export/", CatalogExportView.as_view(), name="admin-catalog-export"),
    path("admin/catalog/template/", CatalogTemplateView.as_view(), name="admin-catalog-template"),
    path("admin/payment-settings/", PaymentSettingsView.as_view(), name="admin-payment-settings"),
    *router.urls,
]
