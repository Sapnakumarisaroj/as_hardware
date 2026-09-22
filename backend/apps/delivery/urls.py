from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AssignmentViewSet, DeliveryMeView, EarningsView

router = SimpleRouter()
router.register("delivery/assignments", AssignmentViewSet, basename="delivery-assignment")

urlpatterns = [
    path("delivery/me/", DeliveryMeView.as_view(), name="delivery-me"),
    path("delivery/earnings/", EarningsView.as_view(), name="delivery-earnings"),
    *router.urls,
]
