from rest_framework.routers import SimpleRouter

from .views import InventoryViewSet, StockMovementViewSet

router = SimpleRouter()
# Register movements first so "movements" isn't captured as an inventory pk.
router.register("inventory/movements", StockMovementViewSet, basename="stock-movement")
router.register("inventory", InventoryViewSet, basename="inventory")

urlpatterns = router.urls
