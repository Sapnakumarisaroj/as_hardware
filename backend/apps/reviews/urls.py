from rest_framework.routers import SimpleRouter

from .views import MyReviewViewSet

router = SimpleRouter()
router.register("reviews/mine", MyReviewViewSet, basename="my-review")

urlpatterns = router.urls
