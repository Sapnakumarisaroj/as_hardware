from django.urls import path
from rest_framework.routers import SimpleRouter

from .image_views import ImageSearchHistoryViewSet, ImageSearchView
from .views import AIConversationViewSet, AssistantStatusView
from .voice_views import VoiceCommandView, VoiceSessionViewSet, VoiceSpeakView, VoiceStatusView, VoiceTranscribeView

router = SimpleRouter()
router.register("ai/conversations", AIConversationViewSet, basename="ai-conversation")
router.register("ai/image-searches", ImageSearchHistoryViewSet, basename="ai-image-search-history")
router.register("ai/voice-sessions", VoiceSessionViewSet, basename="ai-voice-session")

urlpatterns = [
    path("ai/assistant/", AssistantStatusView.as_view(), name="ai-assistant"),
    path("ai/image-search/", ImageSearchView.as_view(), name="ai-image-search"),
    path("ai/voice/", VoiceStatusView.as_view(), name="ai-voice"),
    path("ai/voice/command/", VoiceCommandView.as_view(), name="ai-voice-command"),
    path("ai/voice/transcribe/", VoiceTranscribeView.as_view(), name="ai-voice-transcribe"),
    path("ai/voice/speak/", VoiceSpeakView.as_view(), name="ai-voice-speak"),
    *router.urls,
]
