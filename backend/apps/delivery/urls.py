from django.urls import path
from rest_framework.routers import SimpleRouter

from .api import (
    CartDeliveryEstimateView,
    DeliveryZonesView,
    ProductDeliveryEstimateView,
    ServiceabilityView,
    ShipmentViewSet,
    StoreAvailabilityView,
)
from .views import AssignmentViewSet, DeliveryMeView, EarningsView

router = SimpleRouter()
router.register("delivery/assignments", AssignmentViewSet, basename="delivery-assignment")
router.register("delivery/shipments", ShipmentViewSet, basename="delivery-shipment")

urlpatterns = [
    path("delivery/me/", DeliveryMeView.as_view(), name="delivery-me"),
    path("delivery/earnings/", EarningsView.as_view(), name="delivery-earnings"),
    path("delivery/zones/", DeliveryZonesView.as_view(), name="delivery-zones"),
    path("delivery/check/", ServiceabilityView.as_view(), name="delivery-check"),
    path("delivery/estimate/", ProductDeliveryEstimateView.as_view(), name="delivery-estimate"),
    path("delivery/cart-estimate/", CartDeliveryEstimateView.as_view(), name="delivery-cart-estimate"),
    path("stores/availability/", StoreAvailabilityView.as_view(), name="store-availability"),
    *router.urls,
]
