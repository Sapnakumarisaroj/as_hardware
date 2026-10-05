from django.urls import path
from rest_framework.routers import SimpleRouter

from .api import (
    AdminCashbackRuleViewSet,
    AdminCustomerWalletView,
    AdminLedgerViewSet,
    AdminLoyaltySettingsView,
    AdminPromoCreditView,
    AdminReferralView,
    LedgerViewSet,
    ReferralClaimView,
    WalletView,
)

router = SimpleRouter(trailing_slash=True)
router.register("loyalty/ledger", LedgerViewSet, basename="loyalty-ledger")
router.register("admin/loyalty/ledger", AdminLedgerViewSet, basename="admin-loyalty-ledger")
router.register("admin/loyalty/cashback-rules", AdminCashbackRuleViewSet, basename="admin-cashback-rule")

urlpatterns = [
    path("loyalty/wallet/", WalletView.as_view(), name="loyalty-wallet"),
    path("loyalty/referral/", ReferralClaimView.as_view(), name="loyalty-referral"),
    path("admin/loyalty/settings/", AdminLoyaltySettingsView.as_view(), name="admin-loyalty-settings"),
    path("admin/loyalty/promo-credits/", AdminPromoCreditView.as_view(), name="admin-promo-credits"),
    path("admin/loyalty/customers/<int:user_id>/", AdminCustomerWalletView.as_view(), name="admin-loyalty-customer"),
    path("admin/loyalty/referrals/", AdminReferralView.as_view(), name="admin-loyalty-referrals"),
    *router.urls,
]
