from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AdminBundleViewSet,
    AdminRecommendationRuleViewSet,
    BudgetView,
    BundleAddToCartView,
    BundleListView,
    BundlePriceView,
    RecommendationsView,
    SmartCartView,
)

router = SimpleRouter()
router.register("admin/bundles", AdminBundleViewSet, basename="admin-bundle")
router.register("admin/recommendation-rules", AdminRecommendationRuleViewSet, basename="admin-recommendation-rule")

urlpatterns = [
    path("shopping/recommendations/", RecommendationsView.as_view(), name="shopping-recommendations"),
    path("shopping/cart/", SmartCartView.as_view(), name="shopping-cart"),
    path("shopping/budget/", BudgetView.as_view(), name="shopping-budget"),
    path("shopping/bundles/", BundleListView.as_view(), name="shopping-bundles"),
    path("shopping/bundles/<slug:slug>/price/", BundlePriceView.as_view(), name="shopping-bundle-price"),
    path("shopping/bundles/<slug:slug>/add-to-cart/", BundleAddToCartView.as_view(), name="shopping-bundle-add"),
    *router.urls,
]
