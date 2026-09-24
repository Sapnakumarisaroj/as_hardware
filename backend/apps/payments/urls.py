from django.urls import path

from .views import VerifyPaymentView

urlpatterns = [
    path("payments/<uuid:public_id>/verify/", VerifyPaymentView.as_view(), name="payment-verify"),
]
