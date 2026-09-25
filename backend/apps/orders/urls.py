from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CheckoutPreviewView, OrderViewSet, ReturnViewSet

router = SimpleRouter()
router.register("orders", OrderViewSet, basename="order")
router.register("returns", ReturnViewSet, basename="return")

urlpatterns = [
    path("checkout/preview/", CheckoutPreviewView.as_view(), name="checkout-preview"),
    *router.urls,
]
