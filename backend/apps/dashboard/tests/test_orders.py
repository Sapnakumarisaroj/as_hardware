"""Order management: search, filters, detail, and the returns and refunds lists."""

import pytest

from apps.core.testing import create_product, create_store
from apps.delivery.tests.helpers import assign, create_partner, packed_order, store_at, zone_for
from apps.orders.models import ReturnRequest
from apps.orders.services import cancel_order_by_customer
from apps.orders.tests.helpers import deliver, order_with, pay
from apps.payments.models import Refund

pytestmark = pytest.mark.django_db


@pytest.fixture
def orders(user, other_user, admin_user):
    store = create_store(name="Kothrud")
    _, drill = create_product(name="Drill", price="1000.00", stock=20, store=store)
    _, primer = create_product(name="Primer", price="300.00", mrp="300.00", stock=20, store=store)
    delivered, _ = order_with(user, (drill, 1))
    deliver(delivered, admin_user)
    online, payment = order_with(other_user, (primer, 2), method="online")
    pay(online, payment)
    refunded, payment = order_with(other_user, (drill, 1), method="online")
    pay(refunded, payment)
    refunded.refresh_from_db()
    cancel_order_by_customer(refunded, user=other_user, reason="Changed my mind")
    return {"store": store, "delivered": delivered, "online": online, "refunded": refunded}


def numbers(client, query=""):
    response = client.get(f"/api/admin/orders/?{query}")
    assert response.status_code == 200, response.data
    return {o["order_number"] for o in response.data["results"]}


def test_order_list_shows_who_what_and_where(orders, admin_client, user):
    rows = {o["order_number"]: o for o in admin_client.get("/api/admin/orders/").data["results"]}
    row = rows[orders["delivered"].order_number]
    assert row["customer"]["name"] == "Asha Kumar"
    assert row["customer"]["email"] == user.email
    assert row["store_name"] == "Kothrud"
    assert row["status"] == "delivered"
    assert row["payment_status"] == "paid"
    assert row["item_count"] == 1
    assert rows[orders["refunded"].order_number]["refund_status"] in ("pending", "processed")


def test_order_search_and_filters(orders, admin_client, user, other_user):
    delivered, online, refunded = (orders[k].order_number for k in ("delivered", "online", "refunded"))

    assert numbers(admin_client, f"q={delivered[-6:]}") == {delivered}
    assert numbers(admin_client, "q=asha") == {delivered}
    assert numbers(admin_client, f"q={other_user.email}") == {online, refunded}
    assert numbers(admin_client, "q=primer") == {online}
    assert numbers(admin_client, "status=delivered") == {delivered}
    assert numbers(admin_client, "status=cancelled") == {refunded}
    assert numbers(admin_client, "status=open") == {online}
    assert numbers(admin_client, "status=closed") == {delivered, refunded}
    assert numbers(admin_client, "payment_method=cod") == {delivered}
    assert numbers(admin_client, f"customer={user.pk}") == {delivered}
    assert numbers(admin_client, f"store={orders['store'].pk}") == {delivered, online, refunded}
    assert numbers(admin_client, "from=2000-01-01&to=2000-01-31") == set()
    assert admin_client.get("/api/admin/orders/?from=nonsense").status_code == 400


def test_order_list_is_paginated(orders, admin_client):
    page = admin_client.get("/api/admin/orders/?page_size=2").data
    assert page["count"] == 3
    assert len(page["results"]) == 2
    assert page["next"]


def test_order_detail_has_everything_staff_need(admin_client, admin_user, user):
    store = store_at(0, name="Kothrud")
    zone_for(store)
    _, variant = create_product(name="Drill", stock=5, store=store)
    order = packed_order(user, (variant, 2), km_north=1)
    rider = create_partner(store)
    assign(order.shipments.get(), rider, actor=admin_user)

    data = admin_client.get(f"/api/admin/orders/{order.order_number}/").data
    assert data["customer"]["email"] == user.email
    assert [(i["product_name"], i["quantity"]) for i in data["items"]] == [("Drill", 2)]
    assert data["payment_status"] == "pending"
    assert data["can_manage"] is True
    shipment = data["staff_shipments"][0]
    assert shipment["store_name"] == "Kothrud"
    assert shipment["rider"]["full_name"] == rider.user.full_name
    # A rider is in charge: staff can't mark the order picked up or delivered by hand.
    assert not {"picked_up", "out_for_delivery", "delivered"} & {a["status"] for a in data["allowed_actions"]}

    # The delivery code belongs to the customer; staff never see it.
    text = admin_client.get(f"/api/admin/orders/{order.order_number}/").content.decode()
    assert "otp_hash" not in text
    assert "otp_nonce" not in text


def test_allowed_actions_follow_the_state_machine(orders, admin_client):
    confirmed = admin_client.get(f"/api/admin/orders/{orders['online'].order_number}/").data
    targets = [a["status"] for a in confirmed["allowed_actions"]]
    assert targets == ["processing", "cancelled"]

    done = admin_client.get(f"/api/admin/orders/{orders['refunded'].order_number}/").data
    assert done["allowed_actions"] == []

    # The action itself goes through the existing, validated endpoint.
    url = f"/api/orders/{orders['online'].order_number}/transition/"
    assert admin_client.post(url, {"status": "delivered"}, format="json").status_code in (400, 409)
    assert admin_client.post(url, {"status": "processing"}, format="json").status_code == 200


def test_refund_list_search(orders, admin_client, staff_client, staff_user, other_user):
    refund = Refund.objects.get()
    rows = admin_client.get("/api/payments/refunds/").data["results"]
    assert [(r["order_number"], r["customer_name"], r["store_name"]) for r in rows] == [
        (orders["refunded"].order_number, other_user.full_name, "Kothrud")
    ]
    assert rows[0]["amount"] == str(refund.amount)  # the amount calculated at cancellation, unchanged
    assert admin_client.get("/api/payments/refunds/?q=ravi").data["count"] == 1
    assert admin_client.get("/api/payments/refunds/?q=nobody").data["count"] == 0
    assert admin_client.get(f"/api/payments/refunds/?store={orders['store'].pk}").data["count"] == 1

    assert staff_client.get("/api/payments/refunds/").data["count"] == 0  # not this manager's store
    orders["store"].managers.add(staff_user)
    assert staff_client.get("/api/payments/refunds/").data["count"] == 1


def test_return_list_search(orders, admin_client, auth_client, staff_client, user):
    order = orders["delivered"]
    item = order.items.get()
    created = auth_client.post(
        "/api/returns/",
        {
            "order_number": order.order_number,
            "reason": "damaged",
            "description": "Chuck is cracked",
            "items": [{"order_item_id": item.pk, "quantity": 1}],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    number = ReturnRequest.objects.get().return_number

    def found(client, query):
        return [r["return_number"] for r in client.get(f"/api/returns/?{query}").data["results"]]

    assert found(admin_client, f"q={order.order_number}") == [number]
    assert found(admin_client, "q=asha") == [number]
    assert found(admin_client, "q=nobody") == []
    assert found(admin_client, f"store={orders['store'].pk}") == [number]
    assert found(staff_client, "") == []  # another store's return

    has_return = numbers(admin_client, "has_return=true")
    assert has_return == {order.order_number}


def test_staff_never_see_the_customers_delivery_code(admin_client, admin_user, user):
    from apps.delivery.tests.helpers import advance

    store = store_at(0, name="Kothrud")
    zone_for(store)
    _, variant = create_product(name="Drill", stock=5, store=store)
    order = packed_order(user, (variant, 1), km_north=1)
    job = assign(order.shipments.get(), create_partner(store), actor=admin_user)
    advance(job, "out_for_delivery")

    data = admin_client.get(f"/api/admin/orders/{order.order_number}/").data
    assert data["status"] == "out_for_delivery"
    assert [s["delivery_code"] for s in data["shipments"]] == [None]
    assert data["staff_shipments"][0]["rider"]["assignment_status"] == "out_for_delivery"
