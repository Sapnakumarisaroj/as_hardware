from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.reviews.views import ProductReviewsView

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
    path("products/<slug:slug>/reviews/", ProductReviewsView.as_view(), name="product-reviews"),
    path("search/suggest/", SearchSuggestView.as_view(), name="search-suggest"),
    path("search/recent/", RecentSearchView.as_view(), name="search-recent"),
    path("collections/", CollectionListView.as_view(), name="collection-list"),
    path("collections/<slug:slug>/", CollectionDetailView.as_view(), name="collection-detail"),
    path("options/", OptionTypeListView.as_view(), name="option-types"),
    *router.urls,
]
