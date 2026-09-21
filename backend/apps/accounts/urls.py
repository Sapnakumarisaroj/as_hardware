from rest_framework.routers import SimpleRouter

from .views import AddressViewSet

router = SimpleRouter()
router.register("addresses", AddressViewSet, basename="address")

urlpatterns = router.urls
