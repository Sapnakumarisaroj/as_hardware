"""Phase 7: return requests — eligibility, refund money, staff decisions, stock, order status and access."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.exceptions import ServiceError
from apps.core.testing import create_coupon, create_product, create_store
from apps.inventory.models import Inventory, StockMovement
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderStatus, ReturnRequest
from apps.orders.returns import approve_return, paid_amounts, receive_return, request_return
from apps.payments.models import Payment, Refund

from .helpers import deliver, order_with, pay

pytestmark = pytest.mark.django_db
RS = ReturnRequest.Status


@pytest.fixture
def shop(staff_user):
    store = create_store()
    store.managers.add(staff_user)
    _, drill = create_product(name="Drill", price="3000.00", mrp="3500.00", stock=5, store=store)
    _, tape = create_product(name="PTFE Tape", price="70.00", mrp="100.00", stock=50, store=store, gst_rate="5.00")
    return {"store": store, "drill": drill, "tape": tape}


@pytest.fixture
def delivered(user, staff_user, shop):
    """COD order of 1 drill + 2 tapes, delivered."""
    order, _ = order_with(user, (shop["drill"], 1), (shop["tape"], 2))
    return deliver(order, staff_user)


def _items(order, **by_sku):
    return [{"order_item_id": i.id, "quantity": by_sku[i.sku]} for i in order.items.all() if i.sku in by_sku]


def _request(client, order, reason="damaged", details="", **by_sku):
    body = {"order_number": order.order_number, "reason": reason, "details": details, "items": _items(order, **by_sku)}
    return client.post("/api/returns/", body, format="json")


def _stock(store, variant):
    inv = Inventory.objects.get(store=store, variant=variant)
    return inv.available_quantity, inv.reserved_quantity


# --- Money --------------------------------------------------------------------------------


def test_paid_amounts_spread_coupon_and_add_up_exactly(user, staff_user, shop):
    create_coupon("FLAT100", discount_type="fixed", value=Decimal("100"))
    order, _ = order_with(user, (shop["drill"], 1), (shop["tape"], 3), coupon_code="FLAT100")
    paid = paid_amounts(order)
    by_sku = {i.sku: paid[i.id] for i in order.items.all()}
    # nets 3000 / 210 (base 3210): coupon share 93.46 / 6.54
    assert by_sku == {shop["drill"].sku: Decimal("2906.54"), shop["tape"].sku: Decimal("203.46")}
    assert sum(paid.values()) == order.grand_total - order.delivery_fee


def test_returning_every_unit_in_pieces_refunds_exactly_what_was_paid(user, staff_user, shop):
    create_coupon("FLAT100", discount_type="fixed", value=Decimal("100"))
    order, _ = order_with(user, (shop["drill"], 1), (shop["tape"], 3), coupon_code="FLAT100")
    order = deliver(order, staff_user)
    tape_item = order.items.get(sku=shop["tape"].sku)
    refunds = []
    for _ in range(3):
        ret = request_return(order, user=user, items=[{"order_item_id": tape_item.id, "quantity": 1}], reason="damaged")
        approve_return(ret, actor=staff_user)
        ret = receive_return(ret, actor=staff_user)
        refunds.append(ret.refund_amount)
        order.refresh_from_db()
        assert order.status == OrderStatus.DELIVERED  # the drill is still with the customer
    assert sum(refunds) == paid_amounts(order)[tape_item.id] == Decimal("203.46")


# --- Customer requests --------------------------------------------------------------------


def test_request_return_moves_order_and_exposes_it_on_the_order(
    auth_client, delivered, shop, django_capture_on_commit_callbacks
):
    detail = auth_client.get(f"/api/orders/{delivered.order_number}/").json()
    assert detail["can_return"] is True and detail["return_window_ends_at"]
    assert {i["sku"]: i["returnable_quantity"] for i in detail["items"]} == {shop["drill"].sku: 1, shop["tape"].sku: 2}

    with django_capture_on_commit_callbacks(execute=True):
        res = _request(auth_client, delivered, **{shop["tape"].sku: 1})
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["status"] == "requested" and body["refund_amount"] == "70.00"
    assert body["refund_method"] == "manual" and body["can_cancel"] is True
    assert body["items"][0]["quantity"] == 1 and body["items"][0]["sku"] == shop["tape"].sku

    detail = auth_client.get(f"/api/orders/{delivered.order_number}/").json()
    assert detail["status"] == "return_requested" and detail["can_return"] is False
    assert all(i["returnable_quantity"] == 0 for i in detail["items"])
    assert detail["returns"][0]["return_number"] == body["return_number"]
    assert Notification.objects.filter(event="return.requested").count() == 1

    again = _request(auth_client, delivered, **{shop["drill"].sku: 1})
    assert again.status_code == 409 and again.json()["error"]["code"] == "return_open"


@pytest.mark.parametrize(
    ("change", "code", "status"),
    [
        ("too_many", "quantity_not_returnable", 400),
        ("foreign_item", "invalid_item", 400),
        ("other_without_details", "details_required", 400),
        ("window_closed", "return_window_closed", 400),
        ("not_returnable", "quantity_not_returnable", 400),
        ("empty", "validation_error", 400),
    ],
)
def test_request_validation(auth_client, user, staff_user, delivered, shop, change, code, status):
    body = {
        "order_number": delivered.order_number,
        "reason": "damaged",
        "details": "",
        "items": _items(delivered, **{shop["tape"].sku: 1}),
    }
    if change == "too_many":
        body["items"][0]["quantity"] = 3
    elif change == "foreign_item":
        other, _ = order_with(user, (shop["tape"], 1))
        body["items"][0]["order_item_id"] = other.items.get().id
    elif change == "other_without_details":
        body["reason"] = "other"
    elif change == "window_closed":
        Order.objects.filter(pk=delivered.pk).update(delivered_at=timezone.now() - timedelta(days=8))
    elif change == "not_returnable":
        shop["tape"].product.is_returnable = False
        shop["tape"].product.save()
    elif change == "empty":
        body["items"] = []
    res = auth_client.post("/api/returns/", body, format="json")
    assert res.status_code == status, res.json()
    assert res.json()["error"]["code"] == code
    assert not ReturnRequest.objects.exists()


def test_only_delivered_orders_of_the_customer_can_be_returned(auth_client, api_client, other_user, user, shop):
    order, _ = order_with(user, (shop["tape"], 1))
    res = _request(auth_client, order, **{shop["tape"].sku: 1})
    assert res.status_code == 409 and res.json()["error"]["code"] == "order_not_delivered"
    api_client.force_authenticate(other_user)
    assert _request(api_client, order, **{shop["tape"].sku: 1}).status_code == 404


def test_customer_can_cancel_until_the_store_acts(auth_client, staff_client, delivered, shop):
    number = _request(auth_client, delivered, **{shop["tape"].sku: 2}).json()["return_number"]
    res = auth_client.post(f"/api/returns/{number}/cancel/")
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    delivered.refresh_from_db()
    assert delivered.status == OrderStatus.DELIVERED

    number = _request(auth_client, delivered, **{shop["tape"].sku: 2}).json()["return_number"]
    assert staff_client.post(f"/api/returns/{number}/approve/", {}, format="json").status_code == 200
    res = auth_client.post(f"/api/returns/{number}/cancel/")
    assert res.status_code == 409 and res.json()["error"]["code"] == "return_state_invalid"


# --- Staff decisions ----------------------------------------------------------------------


def test_full_return_restocks_records_refund_and_closes_order(
    auth_client, staff_client, delivered, shop, user, django_capture_on_commit_callbacks
):
    store = shop["store"]
    before = {v.sku: _stock(store, v) for v in (shop["drill"], shop["tape"])}
    with django_capture_on_commit_callbacks(execute=True):
        res = _request(auth_client, delivered, **{shop["drill"].sku: 1, shop["tape"].sku: 2})
    number = res.json()["return_number"]

    assert auth_client.post(f"/api/returns/{number}/approve/", {}, format="json").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        res = staff_client.post(f"/api/returns/{number}/approve/", {"note": "Pickup tomorrow"}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "approved"
    with django_capture_on_commit_callbacks(execute=True):
        res = staff_client.post(f"/api/returns/{number}/receive/", {"restock": True}, format="json")
    assert res.status_code == 200, res.json()
    body = res.json()
    assert body["status"] == "received" and body["restocked"] is True
    assert body["refund_amount"] == "3140.00" and body["refund_status"] == "pending"

    for variant, returned in ((shop["drill"], 1), (shop["tape"], 2)):
        available, reserved = before[variant.sku]
        assert _stock(store, variant) == (available + returned, reserved)
    assert StockMovement.objects.filter(movement_type="return", reference_id=number).count() == 2

    refund = Refund.objects.get()
    assert refund.amount == Decimal("3140.00") and refund.payment.provider == Payment.Provider.COD
    delivered.refresh_from_db()
    assert delivered.status == OrderStatus.RETURNED
    assert [h.to_status for h in delivered.status_history.all()][-2:] == ["return_requested", "returned"]
    events = set(Notification.objects.filter(user=user).values_list("event", flat=True))
    assert {"return.requested", "return.approved", "return.received"} <= events
    # Terminal: no more returns, receive can't run twice.
    assert staff_client.post(f"/api/returns/{number}/receive/", {}, format="json").status_code == 409


def test_receive_without_restock_for_damaged_items(auth_client, staff_client, delivered, shop):
    before = _stock(shop["store"], shop["drill"])
    number = _request(auth_client, delivered, **{shop["drill"].sku: 1}).json()["return_number"]
    staff_client.post(f"/api/returns/{number}/approve/", {}, format="json")
    res = staff_client.post(f"/api/returns/{number}/receive/", {"restock": False, "note": "Motor burnt"}, format="json")
    assert res.json()["restocked"] is False and res.json()["decision_note"] == "Motor burnt"
    assert _stock(shop["store"], shop["drill"]) == before
    assert Refund.objects.get().amount == Decimal("3000.00")


def test_reject_needs_a_reason_and_reopens_the_order(
    auth_client, staff_client, delivered, shop, django_capture_on_commit_callbacks
):
    number = _request(auth_client, delivered, **{shop["drill"].sku: 1}).json()["return_number"]
    res = staff_client.post(f"/api/returns/{number}/reject/", {"note": ""}, format="json")
    assert res.status_code == 400 and res.json()["error"]["code"] == "note_required"
    with django_capture_on_commit_callbacks(execute=True):
        res = staff_client.post(f"/api/returns/{number}/reject/", {"note": "Used and scratched"}, format="json")
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    detail = auth_client.get(f"/api/orders/{delivered.order_number}/").json()
    assert detail["status"] == "delivered" and detail["can_return"] is True  # may ask again within the window
    assert Notification.objects.filter(event="return.rejected", body__contains="Used and scratched").exists()
    assert not Refund.objects.exists()


def test_paid_online_order_refunds_to_the_captured_payment(user, staff_user, shop):
    order, payment = order_with(user, (shop["tape"], 1), method="online")
    pay(order, payment)
    order = deliver(order, staff_user)
    ret = request_return(order, user=user, items=_items(order, **{shop["tape"].sku: 1}), reason="wrong_item")
    assert ret.refund_method == ReturnRequest.RefundMethod.ORIGINAL_PAYMENT
    assert ret.refund_amount == Decimal("70.00")  # the ₹40 delivery fee is not refunded
    approve_return(ret, actor=staff_user)
    ret = receive_return(ret, actor=staff_user)
    assert ret.refund.payment_id == payment.pk and ret.refund.status == Refund.Status.PENDING


def test_staff_access_is_limited_to_their_stores(auth_client, api_client, delivered, shop, user):
    number = _request(auth_client, delivered, **{shop["tape"].sku: 1}).json()["return_number"]
    outsider = get_user_model().objects.create_user("mgr2@example.com", "S3cure-pass!", role="store_manager")
    create_store().managers.add(outsider)
    api_client.force_authenticate(outsider)
    assert api_client.get("/api/returns/").json()["count"] == 0
    assert api_client.post(f"/api/returns/{number}/approve/", {}, format="json").status_code == 404
    assert auth_client.get("/api/returns/").json()["count"] == 1
    assert auth_client.get(f"/api/returns/{number}/").status_code == 200


def test_generic_transition_cannot_bypass_the_return_workflow(staff_client, delivered):
    url = f"/api/orders/{delivered.order_number}/transition/"
    for target in ("return_requested", "returned"):
        res = staff_client.post(url, {"status": target}, format="json")
        assert res.status_code == 409 and res.json()["error"]["code"] == "invalid_transition"


def test_returns_admin_actions_use_the_workflow(user, staff_user, delivered, shop):
    ret = request_return(delivered, user=user, items=_items(delivered, **{shop["tape"].sku: 2}), reason="damaged")
    client = Client()
    client.force_login(get_user_model().objects.create_superuser(email="root@example.com", password="Passw0rd!x"))
    changelist = reverse("admin:orders_returnrequest_changelist")
    assert client.get(changelist).status_code == 200
    assert client.get(reverse("admin:orders_returnrequest_change", args=[ret.pk])).status_code == 200
    for action in ("approve", "receive_restock"):
        client.post(changelist, {"action": action, "_selected_action": [ret.pk]})
    ret.refresh_from_db()
    assert ret.status == RS.RECEIVED and ret.restocked and ret.refund is not None
    with pytest.raises(ServiceError):
        receive_return(ret, actor=staff_user)
