"""Phase 26: the customer support API (start, reply, privacy, closed conversations, staff replies)."""

import pytest
from rest_framework.test import APIClient

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product
from apps.notifications.models import Notification
from apps.orders.services import place_order
from apps.support.models import SupportConversation

pytestmark = pytest.mark.django_db
URL = "/api/support/conversations/"


def test_customer_starts_and_continues_a_conversation(auth_client, user):
    _, variant = create_product(stock=3)
    add_item(user, variant.id, 1)
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    res = auth_client.post(
        URL,
        {"subject": "Wrong size", "message": "I ordered the wrong hinge", "order_number": order.order_number},
        format="json",
    )
    assert res.status_code == 201
    conversation = res.json()
    assert conversation["subject"] == "Wrong size" and len(conversation["messages"]) == 1
    reply = auth_client.post(f"{URL}{conversation['id']}/messages/", {"body": "Can I exchange it?"}, format="json")
    assert reply.status_code == 201 and reply.json()["sender_type"] == "customer"
    assert auth_client.get(URL).json()["count"] == 1


def test_an_order_of_someone_else_cannot_be_attached(auth_client, other_user):
    _, variant = create_product(stock=3)
    add_item(other_user, variant.id, 1)
    theirs, _ = place_order(user=other_user, address_id=create_address(other_user).id, payment_method="cod")
    res = auth_client.post(URL, {"subject": "x", "message": "y", "order_number": theirs.order_number}, format="json")
    assert res.status_code == 404 and not SupportConversation.objects.exists()


def test_conversations_are_private(auth_client, other_user):
    other = APIClient()
    other.force_authenticate(other_user)
    mine = auth_client.post(URL, {"subject": "Mine", "message": "Hello"}, format="json").json()
    assert other.get(f"{URL}{mine['id']}/").status_code == 404
    assert other.post(f"{URL}{mine['id']}/messages/", {"body": "Hi"}, format="json").status_code == 404
    assert other.get(URL).json()["count"] == 0
    assert APIClient().get(URL).status_code == 401


def test_admin_reply_is_an_agent_message_and_notifies_the_customer(
    auth_client, admin_client, user, django_capture_on_commit_callbacks
):
    convo = auth_client.post(URL, {"subject": "Delivery time", "message": "When will it come?"}, format="json").json()
    with django_capture_on_commit_callbacks(execute=True):
        res = admin_client.post(f"{URL}{convo['id']}/messages/", {"body": "Tomorrow by noon."}, format="json")
    assert res.status_code == 201 and res.json()["sender_type"] == "agent"
    assert Notification.objects.filter(user=user, event="support.reply", channel="in_app").exists()


def test_closed_conversations_take_no_new_messages(auth_client):
    convo = auth_client.post(URL, {"subject": "Done", "message": "Thanks"}, format="json").json()
    SupportConversation.objects.filter(pk=convo["id"]).update(status=SupportConversation.Status.CLOSED)
    res = auth_client.post(f"{URL}{convo['id']}/messages/", {"body": "One more thing"}, format="json")
    assert res.status_code == 409 and res.json()["error"]["code"] == "conversation_closed"


def test_message_length_is_limited(auth_client):
    res = auth_client.post(URL, {"subject": "x" * 151, "message": "y"}, format="json")
    assert res.status_code == 400
    res = auth_client.post(URL, {"subject": "ok", "message": "y" * 4001}, format="json")
    assert res.status_code == 400
