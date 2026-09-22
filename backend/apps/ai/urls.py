from rest_framework.routers import SimpleRouter

from .views import AIConversationViewSet

router = SimpleRouter()
router.register("ai/conversations", AIConversationViewSet, basename="ai-conversation")

urlpatterns = router.urls
