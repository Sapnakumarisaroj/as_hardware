from django.urls import path
from rest_framework.routers import SimpleRouter

from .image_views import ImageSearchHistoryViewSet, ImageSearchView
from .views import AIConversationViewSet, AssistantStatusView

router = SimpleRouter()
router.register("ai/conversations", AIConversationViewSet, basename="ai-conversation")
router.register("ai/image-searches", ImageSearchHistoryViewSet, basename="ai-image-search-history")

urlpatterns = [
    path("ai/assistant/", AssistantStatusView.as_view(), name="ai-assistant"),
    path("ai/image-search/", ImageSearchView.as_view(), name="ai-image-search"),
    *router.urls,
]
