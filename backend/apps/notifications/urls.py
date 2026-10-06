from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AdminChannelsView,
    AdminChannelSwitchView,
    AdminEventChannelView,
    AdminEventsView,
    AdminLogViewSet,
    AdminPreviewView,
    AdminTemplateViewSet,
    NotificationViewSet,
    PreferencesView,
    WhatsAppWebhookView,
)

router = SimpleRouter()
router.register("admin/notifications/templates", AdminTemplateViewSet, basename="admin-notification-template")
router.register("admin/notifications/log", AdminLogViewSet, basename="admin-notification-log")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path("notifications/preferences/", PreferencesView.as_view(), name="notification-preferences"),
    path("notifications/webhooks/whatsapp/", WhatsAppWebhookView.as_view(), name="notification-whatsapp-webhook"),
    path("admin/notifications/events/", AdminEventsView.as_view(), name="admin-notification-events"),
    path(
        "admin/notifications/events/<str:key>/<str:channel>/",
        AdminEventChannelView.as_view(),
        name="admin-notification-event-channel",
    ),
    path("admin/notifications/preview/", AdminPreviewView.as_view(), name="admin-notification-preview"),
    path("admin/notifications/channels/", AdminChannelsView.as_view(), name="admin-notification-channels"),
    path(
        "admin/notifications/channels/<str:channel>/",
        AdminChannelSwitchView.as_view(),
        name="admin-notification-channel",
    ),
    *router.urls,
]
