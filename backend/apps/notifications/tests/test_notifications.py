"""Phase 23: notifications — routing, opt-in, deduplication, delivery and retries, templates, the
delivery code that is never stored, the inbox and preferences APIs, the admin screens and the signed
WhatsApp webhook."""

import hashlib
import hmac
import io
import json
import urllib.error
from datetime import timedelta

import pytest
from django.core import mail
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomerProfile
from apps.carts.services import add_item
from apps.core.models import AuditLog
from apps.core.testing import create_address, create_product, create_store
from apps.notifications import services, templating, webhooks
from apps.notifications.events import EVENTS
from apps.notifications.models import ChannelSetting, EventSetting, Notification, NotificationTemplate
from apps.orders.services import place_order
from apps.support.models import SupportConversation, SupportMessage
from apps.support.services import post_message, start_conversation
from integrations.messaging import OUTBOX, MessagingError, OutgoingMessage, mask_phone, reset_messaging_providers
from integrations.messaging.providers import MetaWhatsAppProvider

pytestmark = pytest.mark.django_db
S = Notification.Status


@pytest.fixture(autouse=True)
def _providers(settings):
    settings.WHATSAPP_PROVIDER = "mock"
    settings.SMS_PROVIDER = "mock"
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
    _, drill = create_product(name="Drill", price="600.00", mrp="700.00", stock=20, store=store)
    return {"store": store, "drill": drill, "address": create_address(user)}


def cod_order(user, shop, run):
    add_item(user, shop["drill"].id, 1)
    with run(execute=True):
        order, _ = place_order(user=user, address_id=shop["address"].id, payment_method="cod")
    return order


def channels(user, event):
    return set(Notification.objects.filter(user=user, event=event).values_list("channel", flat=True))


def send(user, event="order.delivered", run=None, **context):
    context.setdefault("order_number", "OD1")
    with run(execute=True):
        services.notify(user, event=event, context=context, data={"order_number": context["order_number"]})


# --- Raising and routing -------------------------------------------------------------------------


def test_cod_order_sends_in_app_email_and_whatsapp_after_commit(customer, shop, django_capture_on_commit_callbacks):
    order = cod_order(customer, shop, django_capture_on_commit_callbacks)
    rows = {n.channel: n for n in Notification.objects.filter(user=customer, event="order.confirmed")}
    assert set(rows) == {"in_app", "email", "whatsapp"}
    assert all(n.status == S.SENT for n in rows.values())
    assert order.order_number in rows["in_app"].title and "₹600.00" in rows["in_app"].body
    assert (
        mail.outbox[-1].to == ["customer@example.com"]
        and f"/account/orders/{order.order_number}" in mail.outbox[-1].body
    )
    sent = [m for m in OUTBOX if m["channel"] == "whatsapp"]
    assert len(sent) == 1 and sent[0]["to"] == "919812345678" and sent[0]["template"] == "order_confirmed"
    assert order.order_number in sent[0]["parameters"] and "Asha" in sent[0]["text"]
    assert rows["whatsapp"].recipient == "+91 98•••••678" and rows["whatsapp"].provider_message_id.startswith("mock-")
    # The store hears about it too (no managers yet → administrators; none here, so nobody).
    assert not Notification.objects.filter(event="staff.order_new").exists()


def test_nothing_is_sent_when_the_transaction_rolls_back(customer, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                services.notify(customer, event="order.delivered", context={"order_number": "OD1"})
                raise RuntimeError("order failed")
        except RuntimeError:
            pass
    assert not Notification.objects.exists() and not OUTBOX


def test_unknown_event_is_a_programming_error(customer):
    with pytest.raises(KeyError, match="Unknown notification event"):
        services.notify(customer, event="order.teleported")


def test_whatsapp_needs_the_customers_opt_in(user, django_capture_on_commit_callbacks):
    user.phone = "9812345678"
    user.save(update_fields=["phone"])
    send(user, run=django_capture_on_commit_callbacks)
    assert channels(user, "order.delivered") == {"in_app", "email"} and not OUTBOX


def test_same_event_twice_sends_once(customer, django_capture_on_commit_callbacks):
    for _ in range(2):
        send(customer, run=django_capture_on_commit_callbacks)
    assert Notification.objects.filter(event="order.delivered").count() == 3  # one per channel
    assert len(OUTBOX) == 1


def test_admin_switches_turn_a_channel_or_an_event_off(customer, django_capture_on_commit_callbacks):
    ChannelSetting.objects.create(channel="whatsapp", enabled=False)
    send(customer, run=django_capture_on_commit_callbacks, order_number="OD1")
    assert channels(customer, "order.delivered") == {"in_app", "email"}
    ChannelSetting.objects.filter(channel="whatsapp").update(enabled=True)
    EventSetting.objects.create(event="order.delivered", channel="email", enabled=False)
    send(customer, run=django_capture_on_commit_callbacks, order_number="OD2")
    assert set(Notification.objects.filter(data__order_number="OD2").values_list("channel", flat=True)) == {
        "in_app",
        "whatsapp",
    }


def test_muted_category_stops_updates_but_never_critical_messages(customer, django_capture_on_commit_callbacks):
    prefs = services.preferences(customer)
    prefs.muted_categories = ["orders", "payments"]
    prefs.save()
    send(customer, run=django_capture_on_commit_callbacks)  # orders: muted
    assert channels(customer, "order.delivered") == {"in_app"}  # the in-app history is always kept
    send(customer, "refund.initiated", run=django_capture_on_commit_callbacks, amount="600.00")  # critical
    assert channels(customer, "refund.initiated") == {"in_app", "email", "whatsapp"}


def test_inactive_account_gets_nothing(customer, django_capture_on_commit_callbacks):
    customer.is_active = False
    customer.save(update_fields=["is_active"])
    send(customer, run=django_capture_on_commit_callbacks)
    assert not Notification.objects.exists()


def test_failure_while_routing_never_breaks_the_caller(customer, monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(services, "dispatch", lambda *a, **k: 1 / 0)
    send(customer, run=django_capture_on_commit_callbacks)  # no exception
    assert not Notification.objects.exists()


# --- Delivery, failures, retries ------------------------------------------------------------------


def test_temporary_failure_is_retried_and_permanent_failure_stops(
    customer, settings, django_capture_on_commit_callbacks
):
    settings.BACKGROUND_JOBS_MODE = "cron"
    customer.phone = "9812349999"  # mock: provider outage
    customer.save(update_fields=["phone"])
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="whatsapp")
    with pytest.raises(MessagingError):
        services.deliver(note.pk)
    note.refresh_from_db()
    assert (note.status, note.attempts) == (S.PENDING, 1) and "temporarily" in note.error
    note.attempts = services.MAX_ATTEMPTS - 1
    note.save()
    assert services.deliver(note.pk) == S.FAILED  # last attempt: recorded, not raised

    customer.phone = "9812340000"  # mock: number can't receive messages
    customer.save(update_fields=["phone"])
    note.status, note.attempts = S.PENDING, 0
    note.save()
    assert services.deliver(note.pk) == S.FAILED and Notification.objects.get(pk=note.pk).attempts == 1


def test_no_provider_or_no_phone_is_skipped_not_failed(customer, settings, django_capture_on_commit_callbacks):
    settings.WHATSAPP_PROVIDER = "none"
    reset_messaging_providers()
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="whatsapp")
    assert note.status == S.SKIPPED and "provider" in note.error


def test_email_outage_is_retried(customer, settings, monkeypatch, django_capture_on_commit_callbacks):
    settings.BACKGROUND_JOBS_MODE = "cron"
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="email")

    def down(*args, **kwargs):
        raise ConnectionRefusedError("SMTP down")

    monkeypatch.setattr(services, "send_mail", down)
    with pytest.raises(ConnectionRefusedError):
        services.deliver(note.pk)
    assert Notification.objects.get(pk=note.pk).status == S.PENDING


def test_admin_retries_a_failed_message(customer, admin_client, settings, django_capture_on_commit_callbacks):
    customer.phone = "9812340000"
    customer.save(update_fields=["phone"])
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="whatsapp")
    assert note.status == S.FAILED
    customer.phone = "9812345678"
    customer.save(update_fields=["phone"])
    with django_capture_on_commit_callbacks(execute=True):
        res = admin_client.post(f"/api/admin/notifications/log/{note.pk}/retry/")
    assert res.status_code == 200
    note.refresh_from_db()
    assert note.status == S.SENT and AuditLog.objects.filter(action="notifications.retry").exists()
    in_app = Notification.objects.get(channel="in_app")
    assert admin_client.post(f"/api/admin/notifications/log/{in_app.pk}/retry/").status_code == 400


def test_receipts_move_forward_only(customer, django_capture_on_commit_callbacks):
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="whatsapp")
    services.apply_receipt(note.provider_message_id, "read")
    services.apply_receipt(note.provider_message_id, "delivered")  # late, older receipt
    note.refresh_from_db()
    assert note.provider_status == "read" and note.delivered_at is not None
    services.apply_receipt(note.provider_message_id, "failed", error="Number not on WhatsApp")
    note.refresh_from_db()
    assert note.status == S.FAILED and note.error == "Number not on WhatsApp"
    assert services.apply_receipt("unknown-id", "read") is False


# --- The delivery code -----------------------------------------------------------------------------


def test_delivery_code_is_sent_but_never_stored(user, admin_user, django_capture_on_commit_callbacks):
    from apps.delivery import otp
    from apps.delivery.tests.helpers import advance, assign, create_partner, packed_order, store_at, zone_for

    user.phone = "9812345678"
    user.save(update_fields=["phone"])
    CustomerProfile.objects.filter(user=user).update(whatsapp_opt_in=True)
    store = store_at(0, riders=0)
    zone_for(store)
    _, drill = create_product(name="Drill", price="600.00", mrp="700.00", stock=10, store=store)
    with django_capture_on_commit_callbacks(execute=True):
        order = packed_order(user, (drill, 1), actor=admin_user)
        job = advance(assign(order.shipments.get(), create_partner(store), actor=admin_user), "out_for_delivery")
    code = otp.code_for_customer(job)
    note = Notification.objects.get(event="delivery.otp", channel="whatsapp")
    assert note.status == S.SENT and code not in note.body and "••••••" in note.body
    assert code not in json.dumps(list(Notification.objects.values()), default=str)
    sent = [m for m in OUTBOX if m["template"] == "delivery_code"]
    assert len(sent) == 1 and code in sent[0]["text"] and code in sent[0]["parameters"]
    # The rider was told about the job, the customer about each step.
    assert {"delivery.rider_assigned", "order.picked_up", "order.out_for_delivery"} <= set(
        Notification.objects.filter(user=user).values_list("event", flat=True)
    )
    # A code that is no longer valid is not sent late.
    note.status = S.PENDING
    note.save()
    job.otp_expires_at = timezone.now() - timedelta(minutes=1)
    job.save(update_fields=["otp_expires_at"])
    assert services.deliver(note.pk) == S.SKIPPED


# --- Templates --------------------------------------------------------------------------------------


def test_template_rendering_is_strict_and_secret_aware():
    assert templating.render("Hi {name}", {"name": "Asha"}) == "Hi Asha"
    with pytest.raises(templating.TemplateError):
        templating.render("Hi {name}", {})
    assert templating.render("Code {otp}", {"otp": "123456"}, secret=("otp",)) == "Code ••••••"
    assert templating.validate("{order_number} {__class__} {a.b}", ("order_number",), limit=100) == [
        "Unknown variable(s): {__class__}.",
        "Braces may only wrap a variable name, like {order_number}.",
    ]
    assert templating.variables_in("{b} {a} {b}") == ["b", "a"]


def test_admin_template_is_validated_previewed_used_and_audited(
    customer, admin_client, django_capture_on_commit_callbacks
):
    url = "/api/admin/notifications/templates/"
    bad = admin_client.post(
        url, {"event": "order.delivered", "channel": "email", "body": "Hi {password}"}, format="json"
    )
    assert bad.status_code == 400 and "password" in json.dumps(bad.json())
    wrong_channel = {"event": "delivery.otp", "channel": "email", "body": "{otp}"}
    assert admin_client.post(url, wrong_channel, format="json").status_code == 400
    preview = admin_client.post(
        "/api/admin/notifications/preview/",
        {"event": "order.delivered", "channel": "whatsapp", "body": "Namaste {customer_name}, {order_number} aa gaya!"},
        format="json",
    ).json()
    assert preview["ok"] and preview["body"] == "Namaste Asha, OD2610060001 aa gaya!"
    assert preview["parameters"] == ["Asha", "OD2610060001"]

    body = {
        "event": "order.delivered",
        "channel": "in_app",
        "language": "en",
        "title": "Pahunch gaya",
        "body": "{order_number} delivered, {customer_name}!",
    }  # noqa: E501
    created = admin_client.post(url, body, format="json")
    assert created.status_code == 201
    assert admin_client.post(url, body, format="json").status_code == 400  # one per event/channel/language
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="in_app")
    assert (note.title, note.body) == ("Pahunch gaya", "OD1 delivered, Asha!")
    assert AuditLog.objects.filter(action="notifications.template_create").exists()


def test_a_broken_saved_template_falls_back_to_the_default_words(customer, django_capture_on_commit_callbacks):
    NotificationTemplate.objects.create(event="order.delivered", channel="in_app", body="Hi {not_a_variable}")
    send(customer, run=django_capture_on_commit_callbacks)
    assert Notification.objects.get(channel="in_app").body.startswith("Your order has been delivered")


def test_hindi_customers_get_hindi_words_when_the_shop_wrote_them(customer, django_capture_on_commit_callbacks):
    CustomerProfile.objects.filter(user=customer).update(preferred_language="hi")
    NotificationTemplate.objects.create(
        event="order.delivered",
        channel="in_app",
        language="hi",
        title="डिलीवर हो गया",
        body="ऑर्डर {order_number} पहुँच गया।",
    )  # noqa: E501
    send(customer, run=django_capture_on_commit_callbacks)
    in_app = Notification.objects.get(channel="in_app")
    assert in_app.body == "ऑर्डर OD1 पहुँच गया।" and in_app.language == "hi"
    assert Notification.objects.get(channel="email").body.startswith("Your order")  # no Hindi email words → English


def test_every_default_message_renders_with_its_own_variables():
    for spec in EVENTS.values():
        values = {name: "x" for name in spec.all_variables}
        for channel in spec.allowed:
            title, body = spec.default_text(channel)
            templating.render(title, values)
            templating.render(body, values)
            assert not templating.validate(body, spec.all_variables, limit=templating.LIMITS["body"])


# --- Inbox and preferences ----------------------------------------------------------------------


def test_inbox_is_private_and_tracks_read_state(customer, other_user, auth_client, django_capture_on_commit_callbacks):
    send(customer, run=django_capture_on_commit_callbacks, order_number="OD1")
    send(customer, "refund.initiated", run=django_capture_on_commit_callbacks, order_number="OD1", amount="600.00")
    send(other_user, run=django_capture_on_commit_callbacks, order_number="OD9")
    page = auth_client.get("/api/notifications/").json()
    assert page["count"] == 2 and {r["link"] for r in page["results"]} == {"/account/orders/OD1"}
    assert auth_client.get("/api/notifications/summary/").json() == {"unread": 2}
    assert auth_client.get("/api/notifications/", {"category": "payments"}).json()["count"] == 1
    first = page["results"][0]["id"]
    assert auth_client.post(f"/api/notifications/{first}/read/").json() == {"unread": 1}
    assert auth_client.get("/api/notifications/", {"unread": "1"}).json()["count"] == 1
    assert auth_client.post(f"/api/notifications/{first}/unread/").json() == {"unread": 2}
    theirs = Notification.objects.get(user=other_user, channel="in_app").pk
    assert auth_client.post(f"/api/notifications/{theirs}/read/").status_code == 404
    assert auth_client.post("/api/notifications/read-all/", {}, format="json").json()["unread"] == 0
    assert Notification.objects.get(pk=theirs).read_at is None
    assert APIClient().get("/api/notifications/").status_code == 401


def test_preferences(user, auth_client):
    prefs = auth_client.get("/api/notifications/preferences/").json()
    assert prefs["email"] is True and prefs["whatsapp"] is False and prefs["channels"]["whatsapp"]["needs_phone"]
    refused = auth_client.patch("/api/notifications/preferences/", {"whatsapp": True}, format="json")
    assert refused.status_code == 400
    user.phone = "9812345678"
    user.save(update_fields=["phone"])
    saved = auth_client.patch(
        "/api/notifications/preferences/",
        {"whatsapp": True, "email": False, "muted_categories": ["delivery", "delivery"]},
        format="json",
    ).json()
    assert saved["whatsapp"] and not saved["email"] and saved["muted_categories"] == ["delivery"]
    assert saved["phone"] == mask_phone("9812345678")
    assert CustomerProfile.objects.get(user=user).whatsapp_opt_in
    bad = auth_client.patch("/api/notifications/preferences/", {"muted_categories": ["spam"]}, format="json")
    assert bad.status_code == 400


# --- Administration ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url",
    [
        ("get", "/api/admin/notifications/events/"),
        ("patch", "/api/admin/notifications/events/order.delivered/email/"),
        ("get", "/api/admin/notifications/templates/"),
        ("post", "/api/admin/notifications/preview/"),
        ("get", "/api/admin/notifications/channels/"),
        ("patch", "/api/admin/notifications/channels/whatsapp/"),
        ("get", "/api/admin/notifications/log/"),
        ("post", "/api/admin/notifications/log/retry-failed/"),
    ],
)
def test_admin_endpoints_are_for_administrators_only(method, url, auth_client, staff_client, delivery_user):
    rider = APIClient()
    rider.force_authenticate(delivery_user)
    for client in (auth_client, staff_client, rider):
        assert getattr(client, method)(url, {}, format="json").status_code == 403
    assert getattr(APIClient(), method)(url, {}, format="json").status_code == 401


def test_admin_switches_are_audited_and_in_app_stays_on(admin_client):
    res = admin_client.patch("/api/admin/notifications/channels/whatsapp/", {"enabled": False}, format="json")
    assert res.status_code == 200 and not services.channel_enabled("whatsapp")
    assert (
        admin_client.patch("/api/admin/notifications/channels/in_app/", {"enabled": False}, format="json").status_code
        == 400
    )
    res = admin_client.patch("/api/admin/notifications/events/order.delivered/sms/", {"enabled": True}, format="json")
    assert res.status_code == 200 and services.event_channels(EVENTS["order.delivered"])["sms"] is True
    assert (
        admin_client.patch(
            "/api/admin/notifications/events/delivery.otp/email/", {"enabled": True}, format="json"
        ).status_code
        == 404
    )
    assert AuditLog.objects.filter(action__in=["notifications.channel", "notifications.event_channel"]).count() == 2
    overview = {row["channel"]: row for row in admin_client.get("/api/admin/notifications/channels/").json()["results"]}
    assert overview["whatsapp"]["mock"] and not overview["whatsapp"]["live"] and not overview["whatsapp"]["enabled"]
    events = admin_client.get("/api/admin/notifications/events/").json()["results"]
    otp_event = next(e for e in events if e["key"] == "delivery.otp")
    assert otp_event["secret_variables"] == ["otp"] and [c["channel"] for c in otp_event["channels"]] == [
        "whatsapp",
        "sms",
    ]


def test_delivery_log_filters_and_never_shows_a_full_phone(customer, admin_client, django_capture_on_commit_callbacks):
    send(customer, run=django_capture_on_commit_callbacks)
    rows = admin_client.get("/api/admin/notifications/log/", {"channel": "whatsapp"}).json()["results"]
    assert len(rows) == 1 and rows[0]["recipient"] == "+91 98•••••678"
    assert "9812345678" not in json.dumps(admin_client.get("/api/admin/notifications/log/").json())
    assert admin_client.get("/api/admin/notifications/log/", {"q": "OD1"}).json()["count"] == 3


# --- Other events --------------------------------------------------------------------------------


def test_support_reply_reaches_the_customer(customer, admin_user, django_capture_on_commit_callbacks):
    conversation = start_conversation(user=customer, subject="Drill bit size", message="Which bit for 6 mm plugs?")
    with django_capture_on_commit_callbacks(execute=True):
        post_message(conversation, sender=admin_user, sender_type="agent", body="Use a 6 mm masonry bit.")
        post_message(conversation, sender=customer, sender_type="customer", body="Thanks")  # no self-notification
    note = Notification.objects.get(event="support.reply", channel="in_app")
    assert "Use a 6 mm masonry bit." in note.body and "Drill bit size" in note.body
    assert channels(customer, "support.reply") == {"in_app", "email", "whatsapp"}


def test_late_orders_are_told_once(customer, shop, admin_user, settings, django_capture_on_commit_callbacks):
    order = cod_order(customer, shop, django_capture_on_commit_callbacks)
    order.estimated_delivery_at = timezone.now() - timedelta(minutes=settings.DELIVERY_DELAY_NOTICE_MINUTES + 5)
    order.save(update_fields=["estimated_delivery_at"])
    with django_capture_on_commit_callbacks(execute=True):
        assert services.tell_about_delays() == 1
    with django_capture_on_commit_callbacks(execute=True):
        assert services.tell_about_delays() == 0
    assert channels(customer, "delivery.delayed") == {"in_app", "email"}
    assert Notification.objects.filter(user=admin_user, event="staff.delivery_delayed").exists()


def test_store_managers_hear_about_new_orders(customer, shop, staff_user, django_capture_on_commit_callbacks):
    shop["store"].managers.add(staff_user)
    order = cod_order(customer, shop, django_capture_on_commit_callbacks)
    note = Notification.objects.get(user=staff_user, event="staff.order_new", channel="in_app")
    assert order.order_number in note.title and services.link_for(EVENTS["staff.order_new"], note.data).startswith(
        "/admin/orders/"
    )


# --- Providers and the webhook ----------------------------------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_meta_provider_sends_an_approved_template(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append((req.full_url, req.headers, json.loads(req.data)))
        return _Response(json.dumps({"messages": [{"id": "wamid.1"}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    provider = MetaWhatsAppProvider(access_token="tok", phone_number_id="12345", api_version="v21.0", timeout=5)
    result = provider.send(OutgoingMessage(to="919812345678", text="x", template="order_confirmed", parameters=["OD1"]))
    url, headers, body = calls[0]
    assert result.message_id == "wamid.1" and url == "https://graph.facebook.com/v21.0/12345/messages"
    assert headers["Authorization"] == "Bearer tok"
    assert body["template"]["name"] == "order_confirmed"
    assert body["template"]["components"][0]["parameters"] == [{"type": "text", "text": "OD1"}]
    assert "tok" not in json.dumps(provider.status())
    with pytest.raises(MessagingError, match="template"):
        provider.send(OutgoingMessage(to="919812345678", text="x"))


@pytest.mark.parametrize("code,meta_code,retryable", [(500, 1, True), (429, 4, True), (400, 132001, False)])
def test_meta_errors_say_whether_to_retry(monkeypatch, code, meta_code, retryable):
    def fail(req, timeout):
        body = io.BytesIO(json.dumps({"error": {"message": "nope", "code": meta_code}}).encode())
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, body)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    provider = MetaWhatsAppProvider(access_token="tok", phone_number_id="1", api_version="v21.0", timeout=5)
    with pytest.raises(MessagingError) as exc:
        provider.send(OutgoingMessage(to="91", text="x", template="t"))
    assert exc.value.retryable is retryable


def _signed(client, payload, secret="app-secret"):  # noqa: S107 — test secret
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/notifications/webhooks/whatsapp/",
        body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
    )


def _incoming(message_id, text, phone="919812345678"):
    msg = {"id": message_id, "from": phone, "type": "text", "text": {"body": text}}
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def test_webhook_refuses_unsigned_or_wrongly_signed_posts(settings, api_client):
    url = "/api/notifications/webhooks/whatsapp/"
    settings.WHATSAPP_APP_SECRET = ""
    assert _signed(api_client, _incoming("w1", "hi")).status_code == 403  # no secret set: nothing accepted
    settings.WHATSAPP_APP_SECRET = "app-secret"
    assert api_client.post(url, _incoming("w1", "hi"), format="json").status_code == 403
    assert _signed(api_client, _incoming("w1", "hi"), secret="wrong").status_code == 403
    assert not SupportMessage.objects.exists()


def test_webhook_verification_handshake(settings, api_client):
    url = "/api/notifications/webhooks/whatsapp/"
    settings.WHATSAPP_VERIFY_TOKEN = "verify-me"
    ok = api_client.get(url, {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.content == b"42"
    assert (
        api_client.get(url, {"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "42"}).status_code
        == 403
    )


def test_webhook_receipts_and_customer_messages(customer, settings, api_client, django_capture_on_commit_callbacks):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    send(customer, run=django_capture_on_commit_callbacks)
    note = Notification.objects.get(channel="whatsapp")
    receipt = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": note.provider_message_id, "status": "delivered", "timestamp": "1790000000"}
                            ]
                        }
                    }
                ]
            }
        ]
    }  # noqa: E501
    assert _signed(api_client, receipt).json() == {"receipts": 1, "messages": 0}
    note.refresh_from_db()
    assert note.provider_status == "delivered" and note.delivered_at is not None

    assert _signed(api_client, _incoming("wamid.in1", "Where is my order?")).json()["messages"] == 1
    assert _signed(api_client, _incoming("wamid.in1", "Where is my order?")).json()["messages"] == 0  # redelivery
    _signed(api_client, _incoming("wamid.in2", "Also need screws"))
    conversation = SupportConversation.objects.get(channel="whatsapp")
    assert conversation.user == customer and conversation.messages.count() == 2

    _signed(api_client, _incoming("wamid.in3", "STOP"))
    assert not CustomerProfile.objects.get(user=customer).whatsapp_opt_in

    _signed(api_client, _incoming("wamid.in4", "Price of cement?", phone="919000000001"))
    stranger = SupportConversation.objects.get(contact_phone="9000000001")
    assert stranger.user is None and stranger.channel == "whatsapp"


def test_webhook_rejects_bad_json(settings, api_client):
    settings.WHATSAPP_APP_SECRET = "app-secret"
    body = b"not json"
    signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    res = api_client.post(
        "/api/notifications/webhooks/whatsapp/",
        body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
    )
    assert res.status_code == 400


def test_signature_check_is_constant_time_hmac(settings):
    settings.WHATSAPP_APP_SECRET = "s"
    body = b"{}"
    good = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert webhooks.signature_ok(body, good)
    assert not webhooks.signature_ok(body, good.upper()) and not webhooks.signature_ok(body, "sha1=" + good[7:])
