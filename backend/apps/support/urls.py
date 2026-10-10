from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import MessageAttachmentView, ProductEnquiryView, SupportConversationViewSet

router = SimpleRouter()
router.register("support/conversations", SupportConversationViewSet, basename="support-conversation")

urlpatterns = [
    path("support/product-enquiries/", ProductEnquiryView.as_view(), name="support-product-enquiry"),
    path(
        "support/messages/<int:message_id>/attachments/<int:index>/",
        MessageAttachmentView.as_view(),
        name="support-message-attachment",
    ),
    *router.urls,
]
