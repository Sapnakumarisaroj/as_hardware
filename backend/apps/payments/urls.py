from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import StaffRefundViewSet, VerifyPaymentView, WebhookView

router = SimpleRouter()
router.register("payments/refunds", StaffRefundViewSet, basename="refund")

urlpatterns = [
    path("payments/<uuid:public_id>/verify/", VerifyPaymentView.as_view(), name="payment-verify"),
    path("payments/webhooks/<slug:provider>/", WebhookView.as_view(), name="payment-webhook"),
    *router.urls,
]
