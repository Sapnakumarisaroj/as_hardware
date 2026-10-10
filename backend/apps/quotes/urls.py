from rest_framework.routers import SimpleRouter

from .views import AdminQuoteViewSet, QuoteViewSet

router = SimpleRouter()
router.register("quotes", QuoteViewSet, basename="quote")
router.register("admin/quotes", AdminQuoteViewSet, basename="admin-quote")

urlpatterns = router.urls
