from django.urls import path

from .views import AvailableCouponsView, LiveOffersView

urlpatterns = [
    path("offers/", LiveOffersView.as_view(), name="offers-live"),
    path("coupons/available/", AvailableCouponsView.as_view(), name="coupons-available"),
]
