from django.urls import path
from rest_framework.routers import SimpleRouter

from .api import (
    CartDeliveryEstimateView,
    CodCollectionViewSet,
    DeliveryPromiseView,
    DeliveryZonesView,
    PartnerAvailabilityView,
    ProductDeliveryEstimateView,
    ServiceabilityView,
    ShipmentViewSet,
    StoreAvailabilityView,
)
from .views import AssignmentViewSet, DeliveryLocationView, DeliveryMeView, EarningsView

router = SimpleRouter()
router.register("delivery/assignments", AssignmentViewSet, basename="delivery-assignment")
router.register("delivery/shipments", ShipmentViewSet, basename="delivery-shipment")
router.register("delivery/cod", CodCollectionViewSet, basename="delivery-cod")

urlpatterns = [
    path("delivery/me/", DeliveryMeView.as_view(), name="delivery-me"),
    path("delivery/me/location/", DeliveryLocationView.as_view(), name="delivery-location"),
    path("delivery/earnings/", EarningsView.as_view(), name="delivery-earnings"),
    path("delivery/partners/", PartnerAvailabilityView.as_view(), name="delivery-partners"),
    path("delivery/zones/", DeliveryZonesView.as_view(), name="delivery-zones"),
    path("delivery/check/", ServiceabilityView.as_view(), name="delivery-check"),
    path("delivery/promise/", DeliveryPromiseView.as_view(), name="delivery-promise"),
    path("delivery/estimate/", ProductDeliveryEstimateView.as_view(), name="delivery-estimate"),
    path("delivery/cart-estimate/", CartDeliveryEstimateView.as_view(), name="delivery-cart-estimate"),
    path("stores/availability/", StoreAvailabilityView.as_view(), name="store-availability"),
    *router.urls,
]
