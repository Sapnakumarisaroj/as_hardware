"""WhatsApp in: photos and documents saved as attachments, the staff-only media endpoint, keyword
auto-replies (order status, reorder, product prices; help and unknown wait for staff), opt-out
silence, the 24-hour session window, product enquiries from the website, cart reminders, low-stock
alerts and the quotation events."""

import hashlib
import hmac
import io
import json
import time
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile
from apps.carts.jobs import due_carts, send_cart_reminders
from apps.carts.models import Cart, CartItem
from apps.carts.services import add_item
from apps.core.testing import add_stock, create_address, create_product, create_store
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement
from apps.notifications import services, whatsapp_bot
from apps.notifications.events import EVENTS
from apps.notifications.models import Notification
from apps.orders.models import Order
from apps.orders.services import place_order
from apps.support.models import SupportConversation, SupportMessage
from integrations.messaging import OUTBOX, MediaFile, MessagingError, reset_messaging_providers
from integrations.messaging.providers import MetaWhatsAppProvider

pytestmark = pytest.mark.django_db
URL = "/api/notifications/webhooks/whatsapp/"
SECRET = "app-secret"  # noqa: S105 — test secret


@pytest.fixture(autouse=True)
def _providers(settings):
    settings.WHATSAPP_PROVIDER = "mock"
    settings.WHATSAPP_APP_SECRET = SECRET
    settings.WHATSAPP_AUTO_REPLIES = True
    reset_messaging_providers()
    OUTBOX.clear()
    yield
    reset_messaging_providers()


@pytest.fixture
def customer(user):
    user.phone = "9812345678"
    user.save(update_fields=["phone"])
    CustomerProfile.objects.filter(user=user).update(whatsapp_opt_in=True)
    user.refresh_from_db()
    return user


@pytest.fixture
def shop(user):
    store = create_store()
    _, ply = create_product(name="BWP Plywood 18 mm", price="2450.00", mrp="2800.00", stock=40, store=store)
    _, hinge = create_product(name="Soft-close Hinge", price="180.00", mrp="220.00", stock=3, store=store)
    return {"store": store, "ply": ply, "hinge": hinge, "address": create_address(user)}


def post(client, payload):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(URL, body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature)


def message(message_id, text=None, phone="919812345678", *, at=None, **extra):
    msg = {"id": message_id, "from": phone, "timestamp": str(int(at if at is not None else time.time()))}
    if text is not None:
        msg.update(type="text", text={"body": text})
    msg.update(extra)
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def say(client, text, run, *, message_id=None, **kwargs):
    with run(execute=True):
        res = post(client, message(message_id or f"wamid.{hash(text)}.{time.time_ns()}", text, **kwargs))
    assert res.status_code == 200, res.content
    return res


def bot_replies():
    return list(SupportMessage.objects.filter(sender_type="bot").values_list("body", flat=True))


def delivered_order(user, shop, run):
    add_item(user, shop["ply"].id, 2)
    with run(execute=True):
        order, _ = place_order(user=user, address_id=shop["address"].id, payment_method="cod")
    Order.objects.filter(pk=order.pk).update(status="delivered", delivered_at=timezone.now())
    order.refresh_from_db()
    return order


# --- Media ---------------------------------------------------------------------------------------


def test_photos_and_documents_are_saved_as_attachments(customer, api_client, django_capture_on_commit_callbacks):
    image = {"id": "media-1", "mime_type": "image/jpeg", "sha256": "abc", "caption": "Is this hinge available?"}
    with django_capture_on_commit_callbacks(execute=True):
        post(api_client, message("wamid.m1", type="image", image=image))
        doc = {"id": "media-2", "mime_type": "application/pdf", "filename": "list.pdf"}
        post(api_client, message("wamid.m2", type="document", document=doc))
    first, second = SupportMessage.objects.order_by("id")
    assert first.body == "Is this hinge available?" and "[" not in first.body
    assert first.attachments == [
        {"type": "image", "media_id": "media-1", "caption": "Is this hinge available?", "mime_type": "image/jpeg",
         "sha256": "abc"}
    ]  # fmt: skip
    assert second.attachments[0]["filename"] == "list.pdf" and second.attachments[0]["type"] == "document"
    assert not bot_replies()  # photos wait for staff


class _FakeProvider:
    configured, name = True, "fake"

    def __init__(self, media):
        self.media = media
        self.asked = []

    def fetch_media(self, media_id, *, max_bytes):
        self.asked.append((media_id, max_bytes))
        if isinstance(self.media, Exception):
            raise self.media
        return self.media


def _photo(customer, mime="image/png"):
    conversation = SupportConversation.objects.create(user=customer, channel="whatsapp", contact_phone="9812345678")
    return SupportMessage.objects.create(
        conversation=conversation,
        sender_type="customer",
        body="",
        attachments=[{"type": "image", "media_id": "m-9", "mime_type": mime, "caption": ""}],
    )


def test_media_endpoint_is_for_staff_only(customer, auth_client, admin_client, monkeypatch):
    msg = _photo(customer)
    url = f"/api/support/messages/{msg.pk}/attachments/0/"
    assert auth_client.get(url).status_code == 403  # the customer themself: staff only
    assert APIClient().get(url).status_code == 401
    # The mock provider keeps nothing: a clear 404, never a fake image.
    res = admin_client.get(url)
    assert res.status_code == 404 and res.json()["error"]["code"] == "attachment_unavailable"

    fake = _FakeProvider(MediaFile(content=b"\x89PNG data", mime_type="image/png"))
    monkeypatch.setattr("integrations.messaging.get_whatsapp_provider", lambda: fake)
    res = admin_client.get(url)
    assert res.status_code == 200 and res.content == b"\x89PNG data" and res["Content-Type"] == "image/png"
    assert res["X-Content-Type-Options"] == "nosniff" and fake.asked[0][0] == "m-9"
    assert admin_client.get(f"/api/support/messages/{msg.pk}/attachments/1/").status_code == 404


def test_media_endpoint_refuses_other_types_and_large_files(customer, admin_client, staff_client, monkeypatch):
    svg = _photo(customer, mime="image/svg+xml")
    assert admin_client.get(f"/api/support/messages/{svg.pk}/attachments/0/").status_code == 404
    msg = _photo(customer)
    url = f"/api/support/messages/{msg.pk}/attachments/0/"
    fake = _FakeProvider(MediaFile(content=b"<html>", mime_type="text/html"))  # lies about the type
    monkeypatch.setattr("integrations.messaging.get_whatsapp_provider", lambda: fake)
    assert admin_client.get(url).status_code == 404
    fake.media = MessagingError("This file is too large to open here.", code="media_too_large")
    assert "too large" in admin_client.get(url).json()["error"]["message"]
    # A store manager sees only conversations about their stores' orders, like the inbox.
    fake.media = MediaFile(content=b"x", mime_type="image/png")
    assert staff_client.get(url).status_code == 404


def test_meta_provider_fetches_media_with_the_token_and_sends_session_text(monkeypatch):
    calls = []

    class _Res(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(req, timeout):
        calls.append((req.full_url, req.get_method(), req.headers.get("Authorization"), req.data))
        if req.full_url.startswith("https://lookaside"):
            return _Res(b"jpegbytes")
        if req.full_url.endswith("/m-1"):
            return _Res(json.dumps({"url": "https://lookaside.example/m-1", "mime_type": "image/jpeg"}).encode())
        return _Res(json.dumps({"messages": [{"id": "wamid.out"}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    provider = MetaWhatsAppProvider(access_token="tok", phone_number_id="123", api_version="v21.0", timeout=5)
    media = provider.fetch_media("m-1", max_bytes=100)
    assert media == MediaFile(content=b"jpegbytes", mime_type="image/jpeg")
    assert [c[2] for c in calls] == ["Bearer tok", "Bearer tok"]
    with pytest.raises(MessagingError, match="too large"):
        provider.fetch_media("m-1", max_bytes=4)
    result = provider.send_text("919812345678", "Your order is on its way")
    body = json.loads(calls[-1][3])
    assert result.message_id == "wamid.out" and body["type"] == "text" and body["text"]["body"].startswith("Your")


# --- Intents -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,kind",
    [
        ("order status", "order_status"),
        ("Mera order kahan hai?", "order_status"),
        ("status", "order_status"),
        ("reorder", "reorder"),
        ("dobara bhej do", "reorder"),
        ("same order please", "reorder"),
        ("price of 18mm plywood", "product"),
        ("kabza hai?", "product"),
        ("help", "help"),
        ("I want to talk to an agent", "help"),
        ("hello", None),
        ("thanks", None),
    ],
)
def test_keyword_intents(text, kind):
    intent = whatsapp_bot.detect(text)
    assert (intent.kind if intent else None) == kind
    if kind == "product" and "plywood" in text:
        assert intent.query == "18 mm plywood"


def test_order_status_reply_uses_the_latest_order(customer, shop, api_client, django_capture_on_commit_callbacks):
    order = delivered_order(customer, shop, django_capture_on_commit_callbacks)
    say(api_client, "mera order kahan hai", django_capture_on_commit_callbacks)
    (reply,) = bot_replies()
    assert order.order_number in reply and "Delivered" in reply and f"/account/orders/{order.order_number}" in reply
    sent = [m for m in OUTBOX if m["text"] == reply]
    assert sent and sent[0]["to"] == "919812345678" and not sent[0]["template"]  # free-form session reply


def test_reorder_puts_items_in_the_cart_and_never_places_an_order(
    customer, shop, api_client, django_capture_on_commit_callbacks
):
    order = delivered_order(customer, shop, django_capture_on_commit_callbacks)
    orders_before = Order.objects.count()
    say(api_client, "same order again", django_capture_on_commit_callbacks)
    (reply,) = bot_replies()
    assert CartItem.objects.get(cart__user=customer).quantity == 2
    assert Order.objects.count() == orders_before and order.order_number in reply and "/cart" in reply
    assert "BWP Plywood 18 mm" in reply and "× 2" in reply


def test_product_enquiry_lists_real_products_and_links_the_conversation(
    customer, shop, api_client, django_capture_on_commit_callbacks
):
    say(api_client, "price of 18mm plywood", django_capture_on_commit_callbacks)
    (reply,) = bot_replies()
    product = shop["ply"].product
    assert "BWP Plywood 18 mm: ₹2,450 (In stock)" in reply and f"/p/{product.slug}" in reply
    assert SupportConversation.objects.get(channel="whatsapp").product == product
    say(api_client, "kabza hai?", django_capture_on_commit_callbacks)  # Hinglish: kabza → hinge
    assert "Soft-close Hinge: ₹180 (Only a few left)" in bot_replies()[-1]


def test_help_and_unknown_messages_wait_for_staff(customer, shop, api_client, django_capture_on_commit_callbacks):
    say(api_client, "I need help with my bill", django_capture_on_commit_callbacks)
    say(api_client, "hello", django_capture_on_commit_callbacks)
    say(api_client, "price of unobtainium widgets", django_capture_on_commit_callbacks)  # nothing found
    assert not bot_replies() and SupportMessage.objects.filter(sender_type="customer").count() == 3


def test_opted_out_numbers_get_nothing(customer, shop, api_client, django_capture_on_commit_callbacks):
    say(api_client, "STOP", django_capture_on_commit_callbacks)
    assert not CustomerProfile.objects.get(user=customer).whatsapp_opt_in
    say(api_client, "order status", django_capture_on_commit_callbacks)
    say(api_client, "price of plywood", django_capture_on_commit_callbacks)
    assert not bot_replies() and not OUTBOX


def test_strangers_get_product_answers_but_no_order_details(shop, api_client, django_capture_on_commit_callbacks):
    say(api_client, "order status", django_capture_on_commit_callbacks, phone="919000000001")
    assert not bot_replies()
    say(api_client, "plywood price", django_capture_on_commit_callbacks, phone="919000000001")
    assert "BWP Plywood" in bot_replies()[0] and OUTBOX[-1]["to"] == "919000000001"


def test_no_free_form_reply_outside_the_24_hour_window(customer, shop, api_client, django_capture_on_commit_callbacks):
    old = time.time() - 25 * 3600  # Meta redelivered a day-old message
    say(api_client, "price of plywood", django_capture_on_commit_callbacks, at=old)
    assert not bot_replies() and SupportMessage.objects.filter(sender_type="customer").count() == 1
    now = timezone.now()
    assert whatsapp_bot.within_session(now - timedelta(hours=23), now)
    assert not whatsapp_bot.within_session(now - timedelta(hours=24), now)
    assert not whatsapp_bot.within_session(None, now)


def test_auto_replies_can_be_switched_off(customer, shop, api_client, settings, django_capture_on_commit_callbacks):
    settings.WHATSAPP_AUTO_REPLIES = False
    say(api_client, "price of plywood", django_capture_on_commit_callbacks)
    assert not bot_replies()


# --- Product enquiry from the website ------------------------------------------------------------


def test_customer_asks_about_a_product(auth_client, user, shop, admin_client):
    product = shop["ply"].product
    res = auth_client.post(
        "/api/support/product-enquiries/", {"product_id": product.pk, "message": "Is it termite proof?"}, format="json"
    )
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["subject"] == f"Question about {product.name}" and body["product"]["slug"] == product.slug
    assert body["messages"][0]["body"] == "Is it termite proof?"
    conversation = SupportConversation.objects.get(pk=body["id"])
    assert conversation.product == product and conversation.user == user
    inbox = admin_client.get(f"/api/admin/support/{conversation.pk}/").json()
    assert inbox["product"]["id"] == product.pk and inbox["messages"][0]["attachments"] == []
    missing = auth_client.post("/api/support/product-enquiries/", {"product_id": 999999, "message": "?"}, format="json")
    assert missing.status_code == 404
    anon = APIClient().post("/api/support/product-enquiries/", {"product_id": product.pk, "message": "x"})
    assert anon.status_code == 401


# --- Cart reminders ------------------------------------------------------------------------------


def _age_cart(user, hours):
    when = timezone.now() - timedelta(hours=hours)
    CartItem.objects.filter(cart__user=user).update(updated_at=when, created_at=when)


def test_cart_reminder_selection_and_one_per_change(
    customer, shop, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.CART_REMINDERS_ENABLED, settings.CART_REMINDER_HOURS = True, 6
    monkeypatch.setattr("apps.carts.jobs.in_quiet_hours", lambda now: False)
    noon = None  # now
    add_item(customer, shop["ply"].id, 2)
    _age_cart(customer, 2)
    assert send_cart_reminders(noon) == 0  # touched 2 hours ago
    _age_cart(customer, 7)
    assert list(due_carts(timezone.now())) == [Cart.objects.get(user=customer)]
    with django_capture_on_commit_callbacks(execute=True):
        assert send_cart_reminders(noon) == 1
        assert send_cart_reminders(noon) == 0  # already reminded for this change
    note = Notification.objects.get(user=customer, event="cart.reminder", channel="in_app")
    assert "2 item(s)" not in note.title  # one line (2 units)
    assert note.title == "You left 1 item(s) in your cart" and "₹4900.00" in note.body
    assert {"in_app", "email", "whatsapp"} == set(
        Notification.objects.filter(event="cart.reminder").values_list("channel", flat=True)
    )
    # The reminder went out 8 hours ago; the customer then added a hinge 7 hours ago → eligible again.
    Cart.objects.filter(user=customer).update(reminded_at=timezone.now() - timedelta(hours=8))
    add_item(customer, shop["hinge"].id, 1)
    _age_cart(customer, 7)
    with django_capture_on_commit_callbacks(execute=True):
        assert send_cart_reminders(noon) == 1
    assert Notification.objects.filter(event="cart.reminder", channel="in_app").count() == 2


def test_cart_reminders_are_off_by_default_and_quiet_at_night(customer, shop, settings):
    add_item(customer, shop["ply"].id, 1)
    _age_cart(customer, 10)
    settings.CART_REMINDERS_ENABLED = False
    assert send_cart_reminders(timezone.localtime().replace(hour=12)) == 0
    settings.CART_REMINDERS_ENABLED = True
    assert send_cart_reminders(timezone.localtime().replace(hour=23)) == 0
    assert Cart.objects.get(user=customer).reminded_at is None


def test_whatsapp_reminder_only_with_opt_in(user, shop, settings, monkeypatch, django_capture_on_commit_callbacks):
    settings.CART_REMINDERS_ENABLED = True
    monkeypatch.setattr("apps.carts.jobs.in_quiet_hours", lambda now: False)
    add_item(user, shop["ply"].id, 1)  # this customer never turned WhatsApp on
    _age_cart(user, 10)
    with django_capture_on_commit_callbacks(execute=True):
        send_cart_reminders()
    assert set(Notification.objects.filter(event="cart.reminder").values_list("channel", flat=True)) == {
        "in_app",
        "email",
    }


# --- Low stock -----------------------------------------------------------------------------------


def test_low_stock_alert_fires_once_when_crossing(staff_user, admin_user, django_capture_on_commit_callbacks):
    store = create_store()
    store.managers.add(staff_user)
    _, variant = create_product(name="Wood Screws", stock=0, store=store)
    inventory = add_stock(variant, 8, store)
    with django_capture_on_commit_callbacks(execute=True):
        apply_movement(inventory, StockMovement.Type.ADJUSTMENT, -2, reason="count")  # 8 → 6: above
    assert not Notification.objects.filter(event="staff.low_stock").exists()
    with django_capture_on_commit_callbacks(execute=True):
        apply_movement(inventory, StockMovement.Type.ADJUSTMENT, -2, reason="count")  # 6 → 4: crossed
        apply_movement(inventory, StockMovement.Type.ADJUSTMENT, -1, reason="count")  # 4 → 3: already low
    notes = Notification.objects.filter(event="staff.low_stock", channel="in_app")
    assert set(notes.values_list("user", flat=True)) == {staff_user.pk, admin_user.pk}
    assert "Wood Screws" in notes.first().title and "down to 4" in notes.first().body
    with django_capture_on_commit_callbacks(execute=True):
        apply_movement(inventory, StockMovement.Type.PURCHASE, 10, reason="restock")
        apply_movement(inventory, StockMovement.Type.ADJUSTMENT, -10, reason="count")  # crossed again, same day
    assert notes.count() == 2  # deduped per stock row per day
    assert Inventory.objects.get(pk=inventory.pk).available_quantity == 3


# --- Quotations and other events -----------------------------------------------------------------


@pytest.mark.parametrize(
    "event,context,expected",
    [
        ("quote.ready", {"valid_until": "16 Oct 2026"}, "Your quotation QT1 is ready, valid until 16 Oct 2026."),
        ("quote.rejected", {"reason": "Item discontinued"}, "Item discontinued"),
        ("quote.expired", {}, "has ended"),
    ],
)
def test_quote_events_reach_the_customer(customer, event, context, expected, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            customer,
            event=event,
            context={"quote_number": "QT1", **context},
            data={"quote_number": "QT1", "quote_id": 7},
        )
    note = Notification.objects.get(user=customer, event=event, channel="in_app")
    assert expected in note.body
    assert services.link_for(EVENTS[event], note.data) == "/account/quotes/7"


def test_quote_staff_events(admin_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            admin_user,
            event="quote.requested",
            context={"quote_number": "QT1", "customer": "Asha Kumar", "lines": 3},
            data={"quote_id": 7},
        )
        services.notify(
            admin_user,
            event="quote.accepted",
            context={"quote_number": "QT1", "customer": "Asha"},
            data={"quote_id": 7},
        )
    titles = set(Notification.objects.filter(channel="in_app").values_list("title", flat=True))
    assert titles == {"Quote request QT1 from Asha Kumar", "Quotation QT1 accepted"}


def test_order_updates_use_whatsapp_when_opted_in():
    for key in ("order.out_for_delivery", "order.delivered", "delivery.delayed"):
        assert "whatsapp" in EVENTS[key].channels and EVENTS[key].whatsapp_template
    assert EVENTS["order.reorder"].link == "/cart"
