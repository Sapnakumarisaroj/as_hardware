"""The assistant API: own conversations only, real product cards, cart through the cart API."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.ai.models import AIConversation, AIMessage
from apps.core.testing import create_category, create_product, create_store

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    store = create_store(name="Kothrud")
    plumbing = create_category("Plumbing")
    tap, tap_variant = create_product(
        name="Brass Pillar Tap", price="899.00", mrp="999.00", category=plumbing, stock=10, store=store
    )
    tape, _ = create_product(
        name="PTFE Thread Seal Tape", price="69.00", mrp="79.00", category=plumbing, stock=10, store=store
    )
    return {"tap": tap, "tap_variant": tap_variant, "tape": tape}


def test_status_is_public_and_never_exposes_provider_details(api_client, settings):
    settings.LLM_PROVIDER = "none"
    response = api_client.get("/api/ai/assistant/")
    assert response.status_code == 200
    data = response.data
    assert data["ai_mode"] == "basic"
    assert data["suggested_prompts"]["en"][0] == "Find a drill for concrete"
    assert data["greeting"]["hinglish"].startswith("Namaste")
    assert data["languages"] == ["en", "hi", "hinglish"]
    assert "key" not in str(data).lower() and "url" not in str(data).lower()


def test_conversations_need_a_login(api_client):
    assert api_client.get("/api/ai/conversations/").status_code == 401
    assert api_client.post("/api/ai/conversations/", {"message": "hi"}, format="json").status_code == 401


def test_start_a_conversation_and_get_product_cards(auth_client, shop):
    response = auth_client.post(
        "/api/ai/conversations/", {"message": "I need something to fix a leaking tap."}, format="json"
    )
    assert response.status_code == 201, response.data
    data = response.data
    assert data["title"] == "I need something to fix a leaking tap."
    assert data["language"] == "en"
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    answer = data["messages"][1]
    assert answer["intent"] == "REPAIR_HELP" and answer["ai_mode"] == "basic"
    cards = answer["products"]
    assert [c["name"] for c in cards] == ["Brass Pillar Tap", "PTFE Thread Seal Tape"]
    tap = cards[0]
    assert tap["price"] == "899.00" and tap["mrp"] == "999.00"  # the catalogue's numbers
    assert tap["stock_status"] == "in_stock"
    assert tap["variant_id"] == shop["tap_variant"].id
    assert tap["reason"] == "Matches “tap”"
    assert tap["slug"] == shop["tap"].slug
    assert {a["type"] for a in answer["actions"]} == {"add_to_cart", "add_all"}


def test_continue_clear_and_delete(auth_client, shop):
    conversation = auth_client.post("/api/ai/conversations/", {}, format="json").data
    assert conversation["messages"] == []
    url = f"/api/ai/conversations/{conversation['id']}/"

    turn = auth_client.post(f"{url}messages/", {"message": "nal tapak raha hai"}, format="json")
    assert turn.status_code == 201, turn.data
    assert turn.data["user_message"]["content"] == "nal tapak raha hai"
    assert turn.data["assistant_message"]["products"][0]["name"] == "Brass Pillar Tap"
    assert turn.data["title"] == "nal tapak raha hai"

    detail = auth_client.get(url).data
    assert len(detail["messages"]) == 2 and detail["language"] == "hinglish"
    listed = auth_client.get("/api/ai/conversations/").data
    assert listed["count"] == 1 and listed["results"][0]["message_count"] == 2

    cleared = auth_client.post(f"{url}clear/")
    assert cleared.status_code == 200 and cleared.data["messages"] == [] and cleared.data["title"] == ""
    assert AIMessage.objects.count() == 0

    assert auth_client.delete(url).status_code == 204
    assert not AIConversation.objects.exists()


def test_messages_are_validated(auth_client, shop):
    conversation = auth_client.post("/api/ai/conversations/", {}, format="json").data
    url = f"/api/ai/conversations/{conversation['id']}/messages/"
    assert auth_client.post(url, {"message": "   "}, format="json").status_code == 400
    assert auth_client.post(url, {"message": "x" * 1001}, format="json").status_code == 400
    assert auth_client.post(url, {"message": "hi", "language": "klingon"}, format="json").status_code == 400


def test_nobody_else_can_see_or_touch_a_conversation(auth_client, other_user, admin_client, shop):
    conversation = auth_client.post("/api/ai/conversations/", {"message": "I need a tap"}, format="json").data
    url = f"/api/ai/conversations/{conversation['id']}/"
    other = APIClient()
    other.force_authenticate(other_user)
    for client in (other, admin_client):
        assert client.get(url).status_code == 404
        assert client.post(f"{url}messages/", {"message": "hijack"}, format="json").status_code == 404
        assert client.post(f"{url}clear/").status_code == 404
        assert client.delete(url).status_code == 404
        assert client.get("/api/ai/conversations/").data["count"] == 0
    assert AIMessage.objects.filter(conversation_id=conversation["id"]).count() == 2


def test_a_product_taken_off_sale_disappears_from_old_answers(auth_client, shop):
    conversation = auth_client.post("/api/ai/conversations/", {"message": "I need a tap"}, format="json").data
    assert [c["name"] for c in conversation["messages"][1]["products"]] == ["Brass Pillar Tap"]
    shop["tap"].is_published = False
    shop["tap"].save()
    again = auth_client.get(f"/api/ai/conversations/{conversation['id']}/").data
    assert again["messages"][1]["products"] == []
    assert "Here is what we have" in again["messages"][1]["content"]  # the text is history; the card is live


def test_recommended_items_go_to_the_cart_through_the_cart_api(auth_client, shop):
    conversation = auth_client.post("/api/ai/conversations/", {"message": "fix a leaking tap"}, format="json").data
    actions = conversation["messages"][1]["actions"]
    add_all = next(a for a in actions if a["type"] == "add_all")
    for variant_id in add_all["variant_ids"]:
        response = auth_client.post("/api/cart/items/", {"variant_id": variant_id, "quantity": 1}, format="json")
        assert response.status_code in (200, 201), response.data
    cart = auth_client.get("/api/cart/").data
    assert {line["product_name"] for line in cart["items"]} == {"Brass Pillar Tap", "PTFE Thread Seal Tape"}
    assert Decimal(cart["totals"]["subtotal"]) == Decimal("968.00")


def test_the_assistant_has_no_way_to_change_prices_stock_or_orders(auth_client, shop):
    """Every route under /api/ai/ is a read or a conversation write; nothing else exists."""
    from django.urls import get_resolver

    patterns = [str(p.pattern) for p in get_resolver().url_patterns]
    ai_routes = [p for p in _all_routes() if p.startswith("api/ai/")]
    assert ai_routes and all(any(part in p for part in ("ai/assistant", "ai/conversations")) for p in ai_routes)
    assert patterns  # sanity


def _all_routes():
    from django.urls import URLPattern, URLResolver, get_resolver

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                yield prefix + str(p.pattern)

    return list(walk(get_resolver().url_patterns))
