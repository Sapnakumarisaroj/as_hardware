from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CheckoutPreviewView, OrderViewSet

router = SimpleRouter()
router.register("orders", OrderViewSet, basename="order")

urlpatterns = [
    path("checkout/preview/", CheckoutPreviewView.as_view(), name="checkout-preview"),
    *router.urls,
]
