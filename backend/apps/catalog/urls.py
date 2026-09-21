from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.reviews.views import ProductReviewsView

from .views import BrandViewSet, CategoryViewSet, ProductViewSet

router = SimpleRouter(trailing_slash=True)
router.register("categories", CategoryViewSet, basename="category")
router.register("brands", BrandViewSet, basename="brand")
router.register("products", ProductViewSet, basename="product")

urlpatterns = [
    path("products/<slug:slug>/reviews/", ProductReviewsView.as_view(), name="product-reviews"),
    *router.urls,
]
