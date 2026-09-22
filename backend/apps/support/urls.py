from rest_framework.routers import SimpleRouter

from .views import SupportConversationViewSet

router = SimpleRouter()
router.register("support/conversations", SupportConversationViewSet, basename="support-conversation")

urlpatterns = router.urls
