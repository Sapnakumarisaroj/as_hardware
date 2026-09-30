from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AIConversationViewSet, AssistantStatusView

router = SimpleRouter()
router.register("ai/conversations", AIConversationViewSet, basename="ai-conversation")

urlpatterns = [path("ai/assistant/", AssistantStatusView.as_view(), name="ai-assistant"), *router.urls]
