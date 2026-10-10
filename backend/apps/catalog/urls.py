from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.reviews.views import ProductReviewsView

from .compare import ProductCompareView
from .compatibility_views import CompatibilityCheckView, ProductCompatibilityView
from .seo import sitemap_view
from .views import (
    BrandViewSet,
    CategoryViewSet,
    CollectionDetailView,
    CollectionListView,
    OptionTypeListView,
    ProductViewSet,
    RecentSearchView,
    SearchSuggestView,
)

router = SimpleRouter(trailing_slash=True)
router.register("categories", CategoryViewSet, basename="category")
router.register("brands", BrandViewSet, basename="brand")
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("products/compare/", ProductCompareView.as_view(), name="product-compare"),
    path("products/<slug:slug>/reviews/", ProductReviewsView.as_view(), name="product-reviews"),
    path("search/suggest/", SearchSuggestView.as_view(), name="search-suggest"),
    path("search/recent/", RecentSearchView.as_view(), name="search-recent"),
    path("collections/", CollectionListView.as_view(), name="collection-list"),
    path("collections/<slug:slug>/", CollectionDetailView.as_view(), name="collection-detail"),
    path("options/", OptionTypeListView.as_view(), name="option-types"),
    path("seo/sitemap.xml", sitemap_view, name="sitemap"),
    path("compatibility/check/", CompatibilityCheckView.as_view(), name="compatibility-check"),
    path("products/<int:product_id>/compatibility/", ProductCompatibilityView.as_view(), name="product-compatibility"),
    *router.urls,
]
