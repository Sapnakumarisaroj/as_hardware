"""Phase 10 over HTTP: the rider's API, what the customer sees, the staff side, permissions,
and the protection of proof-of-delivery photos."""

import io
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.core.testing import create_product
from apps.delivery.models import DeliveryAssignment, DeliveryPartner
from apps.orders.models import Order, OrderItem
from apps.orders.returns import approve_return, request_return

from .helpers import (
    advance,
    assign,
    create_partner,
    deliver_job,
    delivery_code,
    packed_order,
    photo,
    store_at,
    zone_for,
)

pytestmark = pytest.mark.django_db
A = DeliveryAssignment.Status


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def error(response) -> str:
    return response.json()["error"]["code"]


@pytest.fixture
def shop():
    store = store_at(0, riders=0, name="Kothrud Store", area="Kothrud", phone="02012345678")
    zone_for(store)
    _, drill = create_product(name="Drill", price="600.00", mrp="700.00", stock=10, store=store)
    return {"store": store, "drill": drill, "rider": create_partner(store)}


@pytest.fixture
def job(user, shop, admin_user):
    order = packed_order(user, (shop["drill"], 2), actor=admin_user)
    Order.objects.filter(pk=order.pk).update(customer_note="Call before delivery")
    return assign(order.shipments.get(), shop["rider"], actor=admin_user)


@pytest.fixture
def rider(shop) -> APIClient:
    return client_for(shop["rider"].user)


def url(job, action: str = "") -> str:
    return f"/api/delivery/assignments/{job.pk}/{action + '/' if action else ''}"


# --- Rider: profile and availability ---------------------------------------------------------------


def test_profile_and_availability(rider, shop, job):
    me = rider.get("/api/delivery/me/").json()
    assert me["full_name"] == "Rider rider1" and me["home_store_name"] == "Kothrud Store"
    assert me["status"] == "busy" and me["active_assignments"] == 1 and me["max_active_assignments"] == 1
    assert me["cash_in_hand"] == "0.00"
    res = rider.patch("/api/delivery/me/", {"status": "offline"}, format="json")
    assert res.status_code == 409 and error(res) == "active_delivery"
    # Nothing but the status is writable.
    rider.patch(
        "/api/delivery/me/", {"status": "busy", "is_verified": False, "max_active_assignments": 9}, format="json"
    )
    shop["rider"].refresh_from_db()
    assert shop["rider"].is_verified and shop["rider"].max_active_assignments == 1


def test_going_online_and_offline(shop, rider):
    assert rider.patch("/api/delivery/me/", {"status": "offline"}, format="json").json()["status"] == "offline"
    assert rider.patch("/api/delivery/me/", {"status": "available"}, format="json").json()["status"] == "available"
    DeliveryPartner.objects.filter(pk=shop["rider"].pk).update(is_verified=False, status="offline")
    res = rider.patch("/api/delivery/me/", {"status": "available"}, format="json")
    assert res.status_code == 409 and error(res) == "partner_not_verified"


def test_location_ping(rider, shop):
    res = rider.post("/api/delivery/me/location/", {"latitude": "18.5100", "longitude": "73.8100"}, format="json")
    assert res.status_code == 204
    shop["rider"].refresh_from_db()
    assert shop["rider"].current_latitude == Decimal("18.510000") and shop["rider"].last_location_at
    assert (
        rider.post("/api/delivery/me/location/", {"latitude": "95", "longitude": "1"}, format="json").status_code == 400
    )


# --- Rider: a delivery, step by step ---------------------------------------------------------------


def test_job_as_the_rider_sees_it(rider, job, shop):
    data = rider.get(url(job)).json()
    assert data["kind"] == "delivery" and data["status"] == "assigned" and data["status_label"] == "Assigned"
    assert data["next_actions"] == ["accept", "reject"] and data["otp_state"] == "none"
    assert data["payment_method"] == "cod" and data["amount_to_collect"] == "1200.00"
    assert data["cod"] == {
        "amount_due": "1200.00", "collected": False, "collected_amount": None, "method": None,
        "collected_at": None, "handed_over": False, "handed_over_at": None,
    }  # fmt: skip
    assert data["items"] == [{"name": "Drill", "variant": "", "sku": shop["drill"].sku, "quantity": 2}]

    pickup = data["pickup"]
    assert pickup["name"] == "Kothrud Store" and pickup["phone"] == "02012345678"
    assert (
        pickup["map_url"] == "https://www.openstreetmap.org/?mlat=18.507400&mlon=73.807700#map=17/18.507400/73.807700"
    )
    assert pickup["geo_uri"] == "geo:18.507400,73.807700?q=18.507400,73.807700"

    drop = data["drop"]  # customer contact and address, for navigation and calls
    assert drop["name"] == "Asha Kumar" and drop["phone"] == "9876543210" and drop["postal_code"] == "411038"
    assert drop["address"] == "12 MG Road, Pune, 411038" and drop["note"] == "Call before delivery"
    assert drop["directions_url"] == "https://www.openstreetmap.org/directions?to=18.525400%2C73.807700"
    # No prices of items, no totals beyond the amount to collect, no email of the customer.
    flat = str(data)
    assert "unit_price" not in flat and "customer@example.com" not in flat and "grand_total" not in flat


def test_address_without_a_map_pin_gets_search_links(rider, job):
    snapshot = {**job.order.address_snapshot, "latitude": None, "longitude": None}
    Order.objects.filter(pk=job.order_id).update(address_snapshot=snapshot)
    drop = rider.get(url(job)).json()["drop"]
    assert drop["map_url"] == "https://www.openstreetmap.org/search?query=12+MG+Road%2C+Pune%2C+411038"
    assert drop["geo_uri"].startswith("geo:0,0?q=12+MG+Road")


def test_full_delivery_over_http(rider, job, auth_client):
    number = job.order.order_number
    assert rider.post(url(job, "accept")).json()["next_actions"] == ["pickup", "reject"]
    picked = rider.post(url(job, "pickup"), {"latitude": "18.5074", "longitude": "73.8077"}, format="json").json()
    assert picked["status"] == "picked_up" and picked["order_status"] == "picked_up" and picked["picked_up_at"]
    started = rider.post(url(job, "start"), {}, format="json").json()
    assert started["status"] == "out_for_delivery" and started["otp_state"] == "active"
    assert started["next_actions"] == ["proof", "complete", "fail"]
    assert "otp" not in started and "delivery_code" not in started  # the rider never gets the code
    assert delivery_code(job) not in str(started)

    notes = rider.patch(url(job, "notes"), {"notes": "Blue gate"}, format="json").json()
    assert notes["delivery_notes"] == "Blue gate"

    code = auth_client.get(f"/api/orders/{number}/").json()["shipments"][0]["delivery_code"]["code"]
    bad = rider.post(url(job, "complete"), {"otp": "000000" if code != "000000" else "111111"}, format="json")
    assert bad.status_code == 400 and error(bad) == "otp_invalid"
    no_cash = rider.post(url(job, "complete"), {"otp": code}, format="json")
    assert no_cash.status_code == 400 and error(no_cash) == "cod_not_collected"
    assert no_cash.json()["error"]["details"] == {"amount_due": "1200.00"}

    body = {"otp": code, "cod_collected": True, "cod_amount": "1200.00", "cod_method": "cash", "received_by": "Asha"}
    done = rider.post(url(job, "complete"), body, format="json")
    assert done.status_code == 200, done.json()
    data = done.json()
    assert data["status"] == "delivered" and data["order_status"] == "delivered" and data["otp_state"] == "used"
    assert data["next_actions"] == [] and data["amount_to_collect"] is None and data["earning_amount"] == "41.20"
    assert data["cod"]["collected"] and data["cod"]["method"] == "cash" and not data["cod"]["handed_over"]
    # The customer's contact details disappear once the job is over.
    assert data["drop"] == {"area": "", "city": "Pune"}
    again = rider.post(url(job, "complete"), body, format="json")
    assert again.status_code == 409 and error(again) == "invalid_delivery_state"


def test_reject_and_fail_over_http(rider, job):
    assert rider.post(url(job, "reject"), {}, format="json").status_code == 400
    rejected = rider.post(url(job, "reject"), {"reason": "Puncture"}, format="json").json()
    assert rejected["status"] == "rejected" and rejected["reject_reason"] == "Puncture"

    job2 = assign(job.shipment, DeliveryPartner.objects.get(pk=job.partner_id), actor=None)
    advance(job2, "out_for_delivery")
    assert rider.post(url(job2, "fail"), {"reason": "nonsense"}, format="json").status_code == 400
    failed = rider.post(url(job2, "fail"), {"reason": "wrong_address", "note": "No such house"}, format="json").json()
    assert failed["status"] == "failed" and failed["order_status"] == "delivery_failed"
    assert failed["failure_reason"] == "Address wrong or not found: No such house" and failed["otp_state"] == "none"


def test_lists_history_and_earnings(rider, job, user, other_user, shop, admin_user):
    assert [j["id"] for j in rider.get("/api/delivery/assignments/", {"scope": "active"}).json()["results"]] == [job.pk]
    assert rider.get("/api/delivery/assignments/", {"scope": "history"}).json()["results"] == []
    advance(job, "out_for_delivery")
    deliver_job(job)
    order = packed_order(other_user, (shop["drill"], 1), actor=admin_user)
    second = advance(assign(order.shipments.get(), shop["rider"], actor=admin_user), "picked_up")
    rider.post(url(second, "fail"), {"reason": "customer_unavailable"}, format="json")

    history = rider.get("/api/delivery/assignments/", {"scope": "history"}).json()["results"]
    assert [(j["id"], j["status"]) for j in history] == [(second.pk, "failed"), (job.pk, "delivered")]
    assert rider.get("/api/delivery/assignments/", {"scope": "active"}).json()["results"] == []
    assert rider.get("/api/delivery/assignments/", {"kind": "return_pickup"}).json()["results"] == []

    earnings = rider.get("/api/delivery/earnings/").json()
    assert earnings == {
        "delivered_count": 1, "total_earnings": "41.20", "today_earnings": "41.20", "last_7_days_earnings": "41.20",
        "today_delivered_count": 1, "failed_count": 1, "cash_in_hand": "1200.00",
        "cash_deliveries_pending_handover": 1,
    }  # fmt: skip


# --- Permissions -----------------------------------------------------------------------------------

RIDER_ACTIONS = [
    ("post", "accept"), ("post", "reject"), ("post", "pickup"), ("post", "start"), ("post", "complete"),
    ("post", "fail"), ("patch", "notes"), ("post", "proof"), ("get", "proof"), ("get", ""),
]  # fmt: skip


def test_a_rider_reaches_only_their_own_jobs(job, shop):
    stranger = client_for(create_partner(shop["store"], email="stranger@example.com").user)
    for method, action in RIDER_ACTIONS:
        res = getattr(stranger, method)(url(job, action), {"reason": "x", "notes": "x", "otp": "1"}, format="json")
        assert res.status_code == 404, (method, action, res.status_code)
    assert stranger.get("/api/delivery/assignments/").json()["results"] == []
    job.refresh_from_db()
    assert job.status == A.ASSIGNED and job.delivery_notes == ""


def test_only_riders_use_the_rider_api(job, api_client, auth_client, staff_client, admin_client):
    for method, action in RIDER_ACTIONS:
        assert getattr(api_client, method)(url(job, action)).status_code == 401
        for client in (auth_client, staff_client, admin_client):
            assert getattr(client, method)(url(job, action)).status_code == 403, (method, action)
    for path in ("/api/delivery/me/", "/api/delivery/earnings/"):
        assert auth_client.get(path).status_code == 403 and api_client.get(path).status_code == 401
    assert auth_client.post("/api/delivery/me/location/", {}).status_code == 403


def test_a_rider_cannot_edit_orders_prices_or_customers(rider, job, shop, user):
    number, order_before = job.order.order_number, Order.objects.values().get(pk=job.order_id)
    attempts = [
        ("patch", url(job), {"status": "delivered", "earning_amount": "9999", "cod_amount_due": "1"}),
        ("put", url(job), {"status": "delivered"}),
        ("delete", url(job), None),
        ("post", "/api/delivery/assignments/", {"order": job.order_id, "partner": job.partner_id}),
        ("patch", f"/api/orders/{number}/", {"grand_total": "1.00"}),
        ("post", f"/api/orders/{number}/transition/", {"status": "delivered"}),
        ("post", f"/api/orders/{number}/cancel/", {"reason": "x"}),
        ("get", f"/api/orders/{number}/", None),
        ("patch", f"/api/products/{shop['drill'].product.slug}/", {"name": "Hacked"}),
        ("post", f"/api/inventory/{1}/adjust/", {"movement_type": "adjustment", "quantity": 5, "reason": "x"}),
        ("get", "/api/admin/users/", None),
        ("get", "/api/delivery/shipments/", None),
        ("post", f"/api/delivery/shipments/{job.shipment_id}/assign/", {"partner_id": job.partner_id}),
        ("get", "/api/delivery/partners/", None),
        ("get", "/api/delivery/cod/", None),
        ("post", f"/api/delivery/cod/{job.pk}/handover/", {}),
    ]
    for method, path, body in attempts:
        res = getattr(rider, method)(path, body, format="json")
        assert res.status_code in (403, 404, 405), (method, path, res.status_code)
    assert Order.objects.values().get(pk=job.order_id) == order_before
    assert OrderItem.objects.get(order=job.order).unit_price == Decimal("600.00")
    job.refresh_from_db()
    assert job.status == A.ASSIGNED and job.cod_amount_due == Decimal("1200.00") and job.earning_amount == 0
    user.refresh_from_db()
    assert user.email == "customer@example.com"
    # Extra fields sent with a real action are ignored.
    rider.post(
        url(job, "accept"), {"earning_amount": "9999", "status": "delivered", "cod_amount_due": "0"}, format="json"
    )
    job.refresh_from_db()
    assert job.status == A.ACCEPTED and job.earning_amount == 0 and job.cod_amount_due == Decimal("1200.00")


# --- Proof of delivery -----------------------------------------------------------------------------


def test_proof_upload_is_cleaned_and_stored_privately(rider, job, django_capture_on_commit_callbacks):
    advance(job, "picked_up")
    early = rider.post(url(job, "proof"), {"photo": photo()}, format="multipart")
    assert early.status_code == 409 and error(early) == "invalid_delivery_state"
    advance(job, "out_for_delivery")

    res = rider.post(url(job, "proof"), {"photo": photo(exif=True, size=(4000, 3000)), "received_by": "Asha"},
                     format="multipart")  # fmt: skip
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["proof_uploaded"] is True and data["received_by"] == "Asha"
    assert "proof_image" not in data and "delivery-proofs" not in str(data)  # no path, no URL

    job.refresh_from_db()
    stored = job.proof_image
    assert stored.name.startswith("delivery-proofs/") and stored.name.endswith(".jpg") and "door" not in stored.name
    assert str(settings.PRIVATE_MEDIA_ROOT) in stored.path and str(settings.MEDIA_ROOT) not in stored.path
    with pytest.raises(ValueError, match="no URL"):
        _ = stored.url
    with stored.open("rb") as handle:
        saved = Image.open(io.BytesIO(handle.read()))
    assert saved.format == "JPEG" and max(saved.size) == 1600
    assert not saved.getexif()  # GPS position, phone model etc. are gone

    first = stored.name
    with django_capture_on_commit_callbacks(execute=True):
        rider.post(url(job, "proof"), {"photo": photo("PNG")}, format="multipart")
    job.refresh_from_db()
    assert job.proof_image.name != first and not job.proof_image.storage.exists(first)  # replaced, not piled up


@pytest.mark.parametrize("kind", ["text", "gif", "huge", "missing", "svg"])
def test_bad_uploads_are_refused(rider, job, kind):
    from django.core.files.uploadedfile import SimpleUploadedFile

    advance(job, "out_for_delivery")
    uploads = {
        "text": SimpleUploadedFile("door.jpg", b"not an image at all", content_type="image/jpeg"),
        "gif": photo("GIF"),
        "svg": SimpleUploadedFile("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", "image/svg+xml"),
        "huge": SimpleUploadedFile("door.jpg", b"\xff\xd8\xff" + b"0" * (9 * 1024 * 1024), content_type="image/jpeg"),
    }
    body = {} if kind == "missing" else {"photo": uploads[kind]}
    res = rider.post(url(job, "proof"), body, format="multipart")
    assert res.status_code == 400, kind
    job.refresh_from_db()
    assert not job.proof_image and job.proof_uploaded_at is None


def test_who_can_see_the_photo(rider, job, shop, auth_client, other_user, api_client, staff_user, admin_client):
    number = job.order.order_number
    advance(job, "out_for_delivery")
    customer_url = f"/api/orders/{number}/shipments/1/proof/"
    staff_url = f"/api/delivery/shipments/{job.shipment_id}/proof/"
    assert rider.get(url(job, "proof")).status_code == 404  # nothing uploaded yet
    rider.post(url(job, "proof"), {"photo": photo()}, format="multipart")

    own = rider.get(url(job, "proof"))
    assert own.status_code == 200 and own["Content-Type"] == "image/jpeg"
    assert own["Cache-Control"] == "private, no-store" and own["X-Content-Type-Options"] == "nosniff"
    assert Image.open(io.BytesIO(b"".join(own.streaming_content))).format == "JPEG"

    # The customer sees it once the delivery is complete, not before.
    assert auth_client.get(customer_url).status_code == 404
    deliver_job(job)
    shipment = auth_client.get(f"/api/orders/{number}/").json()["shipments"][0]
    assert shipment["proof_available"] is True and "proof_image" not in shipment
    assert auth_client.get(customer_url).status_code == 200
    assert auth_client.get(f"/api/orders/{number}/shipments/2/proof/").status_code == 404

    assert api_client.get(customer_url).status_code == 401 and api_client.get(staff_url).status_code == 401
    assert client_for(other_user).get(customer_url).status_code == 404
    assert client_for(other_user).get(staff_url).status_code == 403
    other_rider = client_for(create_partner(shop["store"], email="x@example.com").user)
    assert other_rider.get(url(job, "proof")).status_code == 404
    assert other_rider.get(customer_url).status_code == 404 and other_rider.get(staff_url).status_code == 403

    manager = client_for(staff_user)
    assert manager.get(staff_url).status_code == 404  # not their store
    shop["store"].managers.add(staff_user)
    assert manager.get(staff_url).status_code == 200 and admin_client.get(staff_url).status_code == 200
    assert AuditLog.objects.filter(action="delivery.proof_viewed").count() == 2

    # Not reachable as a media file.
    job.refresh_from_db()
    assert Client().get(f"/{settings.MEDIA_URL.strip('/')}/{job.proof_image.name}").status_code == 404


# --- Customer ------------------------------------------------------------------------------------


def test_customer_follows_the_delivery(auth_client, rider, job, other_user, staff_user, shop):
    number = job.order.order_number

    def view(client=auth_client):
        data = client.get(f"/api/orders/{number}/").json()
        return data, data["shipments"][0]

    order, shipment = view()
    assert (order["status"], shipment["status"], shipment["status_label"]) == (
        "assigned", "assigned", "Delivery partner assigned",
    )  # fmt: skip
    assert shipment["rider"] == {"name": "Rider", "vehicle": "Scooter / bike", "phone": None, "status": "assigned"}
    assert shipment["delivery_code"] is None and shipment["amount_to_pay"] == "1200.00"
    assert order["can_cancel"] is False

    advance(job, "picked_up")
    order, shipment = view()
    assert shipment["status"] == "picked_up" and shipment["rider"]["phone"] == "9123456780"
    assert shipment["picked_up_at"] and shipment["delivery_code"] is None

    advance(job, "out_for_delivery")
    order, shipment = view()
    code = shipment["delivery_code"]
    assert order["status"] == "out_for_delivery" and order["delivery_message"].startswith("Out for delivery")
    assert code["state"] == "active" and code["code"] == delivery_code(job) and code["expires_at"]
    assert code["can_request_new"] is False and shipment["delivery_attempts"] == 1

    # Only the customer who ordered sees the code: not staff, not other customers.
    shop["store"].managers.add(staff_user)
    _, as_staff = view(client_for(staff_user))
    assert as_staff["delivery_code"] is None and as_staff["status"] == "out_for_delivery"
    assert client_for(other_user).get(f"/api/orders/{number}/").status_code == 404
    assert rider.get(f"/api/orders/{number}/").status_code == 404

    too_soon = auth_client.post(f"/api/orders/{number}/shipments/1/delivery-code/")
    assert too_soon.status_code == 409 and error(too_soon) == "otp_too_soon"
    assert client_for(other_user).post(f"/api/orders/{number}/shipments/1/delivery-code/").status_code == 404

    deliver_job(job, received_by="Asha")
    order, shipment = view()
    assert order["status"] == "delivered" and order["delivery_message"] == "Delivered" and order["delivered_at"]
    assert shipment["status"] == "delivered" and shipment["delivered_at"] and shipment["received_by"] == "Asha"
    assert shipment["delivery_code"] is None and shipment["amount_to_pay"] is None
    assert shipment["rider"]["phone"] is None and order["payment_status"] == "paid"
    assert [h["to_status"] for h in order["status_history"]][-3:] == ["picked_up", "out_for_delivery", "delivered"]


def test_customer_gets_a_new_code(auth_client, job):
    from datetime import timedelta

    from django.utils import timezone

    number = job.order.order_number
    advance(job, "out_for_delivery")
    old = delivery_code(job)
    now = timezone.now()
    DeliveryAssignment.objects.filter(pk=job.pk).update(
        otp_expires_at=now - timedelta(minutes=1), otp_issued_at=now - timedelta(minutes=31)
    )
    shown = auth_client.get(f"/api/orders/{number}/").json()["shipments"][0]["delivery_code"]
    assert shown["state"] == "expired" and shown["code"] is None and shown["can_request_new"] is True
    res = auth_client.post(f"/api/orders/{number}/shipments/1/delivery-code/")
    assert res.status_code == 200
    fresh = res.json()["shipments"][0]["delivery_code"]
    assert fresh["state"] == "active" and fresh["code"] and fresh["code"] != old


def test_customer_sees_a_failed_delivery(auth_client, rider, job):
    number = job.order.order_number
    advance(job, "out_for_delivery")
    rider.post(url(job, "fail"), {"reason": "customer_unavailable", "note": "Rang three times"}, format="json")
    order = auth_client.get(f"/api/orders/{number}/").json()
    shipment = order["shipments"][0]
    assert order["status"] == "delivery_failed" and "couldn't deliver" in order["delivery_message"]
    assert shipment["status"] == "failed" and shipment["delivery_code"] is None
    assert shipment["failure"]["code"] == "customer_unavailable"
    assert shipment["failure"]["reason"] == "Customer not available" and shipment["failure"]["failed_at"]
    assert "another delivery attempt" in shipment["failure"]["next_step"]
    assert "Rang three times" not in str(order)  # the rider's note is for the store
    assert order["delivery"]["minutes_left"] is None
    row = auth_client.get("/api/orders/").json()["results"][0]
    assert row["status"] == "delivery_failed"


# --- Staff -----------------------------------------------------------------------------------------


@pytest.fixture
def manager(staff_user, shop) -> APIClient:
    shop["store"].managers.add(staff_user)
    return client_for(staff_user)


def shipments(client, **params):
    return client.get("/api/delivery/shipments/", params).json()["results"]


def test_staff_follow_shipments_and_reassign(manager, job, shop, user):
    second = create_partner(shop["store"], email="second@example.com")
    assert shipments(manager) == []
    (row,) = shipments(manager, scope="active")
    assert row["status"] == "assigned" and row["rider"]["full_name"] == "Rider rider1"
    assert row["rider"]["assignment_status"] == "assigned" and row["cod"]["amount_due"] == "1200.00"
    assert (row["can_assign"], row["can_reassign"]) == (False, True)

    base = f"/api/delivery/shipments/{job.shipment_id}/"
    res = manager.post(base + "reassign/", {"partner_id": second.pk, "reason": "Closer"}, format="json")
    assert res.status_code == 201, res.json()
    detail = res.json()
    assert detail["rider"]["partner_id"] == second.pk
    assert [(a["partner_name"], a["status"]) for a in detail["assignments"]] == [
        ("Rider second", "assigned"),
        ("Rider rider1", "cancelled"),
    ]
    assert detail["items"] == [{"name": "Drill", "variant": "", "sku": shop["drill"].sku, "quantity": 2}]
    same = manager.post(base + "reassign/", {"partner_id": second.pk}, format="json")
    assert same.status_code == 409 and error(same) == "same_partner"
    assert manager.post(base + "reassign/", {"partner_id": 999999}, format="json").status_code == 404

    unassigned = manager.post(base + "unassign/", {"reason": "Customer asked for later"}, format="json")
    assert unassigned.status_code == 200 and unassigned.json()["status"] == "pending"
    assert unassigned.json()["rider"] is None and unassigned.json()["can_assign"] is True
    assert [s["id"] for s in shipments(manager)] == [job.shipment_id]
    gone = manager.post(base + "unassign/", {}, format="json")
    assert gone.status_code == 409 and error(gone) == "not_assigned"


def test_staff_send_a_failed_shipment_out_again(manager, rider, job, shop):
    advance(job, "out_for_delivery")
    locked = manager.post(f"/api/delivery/shipments/{job.shipment_id}/reassign/", {"partner_id": 1}, format="json")
    assert locked.status_code in (404, 409)
    rider.post(url(job, "fail"), {"reason": "wrong_address"}, format="json")

    (row,) = shipments(manager, scope="failed")
    assert row["status"] == "failed" and row["failure_reason"] == "wrong_address" and row["delivery_attempts"] == 1
    assert row["can_assign"] is True and [s["id"] for s in shipments(manager)] == [row["id"]]
    detail = manager.get(f"/api/delivery/shipments/{row['id']}/").json()
    assert detail["assignments"][0]["failure_reason"] == "Address wrong or not found"
    assert [h["to_status"] for h in detail["assignments"][0]["status_history"]][-1] == "failed"

    second = create_partner(shop["store"], email="second@example.com")
    res = manager.post(f"/api/delivery/shipments/{row['id']}/assign/", {"partner_id": second.pk}, format="json")
    assert res.status_code == 201 and res.json()["order_status"] == "assigned"
    assert shipments(manager, scope="failed") == []


def test_rider_availability_for_staff(manager, admin_client, job, shop):
    idle = create_partner(shop["store"], email="idle@example.com")
    create_partner(shop["store"], email="off@example.com", status="offline")
    create_partner(store_at(9), email="elsewhere@example.com")
    advance(job, "out_for_delivery")
    deliver_job(job)
    rows = {r["full_name"]: r for r in manager.get("/api/delivery/partners/").json()}
    assert set(rows) == {"Rider rider1", "Rider idle", "Rider off"}  # only riders of their stores
    assert rows["Rider rider1"]["cash_in_hand"] == "1200.00" and rows["Rider rider1"]["status"] == "available"
    assert rows["Rider idle"] == {
        "partner_id": idle.pk, "full_name": "Rider idle", "phone": "9123456780", "vehicle_type": "scooter",
        "home_store_name": "Kothrud Store", "status": "available", "is_verified": True, "is_active": True,
        "active_assignments": 0, "capacity": 1, "can_take_jobs": True, "cash_in_hand": "0.00",
        "last_location_at": None,
    }  # fmt: skip
    assert rows["Rider off"]["can_take_jobs"] is False
    assert [r["full_name"] for r in manager.get("/api/delivery/partners/", {"status": "offline"}).json()] == [
        "Rider off"
    ]
    assert len(admin_client.get("/api/delivery/partners/").json()) == 4


def test_cod_collection_and_handover_for_staff(manager, admin_client, staff_user, job, shop, api_client):
    advance(job, "out_for_delivery")
    assert manager.get("/api/delivery/cod/").json()["results"] == []
    deliver_job(job)
    (row,) = manager.get("/api/delivery/cod/", {"handed_over": "false"}).json()["results"]
    assert row["order_number"] == job.order.order_number and row["partner_name"] == "Rider rider1"
    assert (row["cod_collected_amount"], row["cod_method"], row["handed_over"]) == ("1200.00", "cash", False)
    assert manager.get("/api/delivery/cod/", {"handed_over": "true"}).json()["results"] == []
    assert manager.get("/api/delivery/cod/", {"partner": job.partner_id}).json()["count"] == 1
    assert manager.get("/api/delivery/cod/", {"partner": "x"}).json()["count"] == 0

    res = manager.post(f"/api/delivery/cod/{job.pk}/handover/", {"note": "Counted"}, format="json")
    assert res.status_code == 200
    assert res.json()["handed_over"] is True and res.json()["handed_over_to"] == staff_user.full_name
    twice = admin_client.post(f"/api/delivery/cod/{job.pk}/handover/", {}, format="json")
    assert twice.status_code == 409 and error(twice) == "cod_already_handed_over"
    assert manager.get("/api/delivery/cod/", {"handed_over": "false"}).json()["results"] == []
    assert api_client.get("/api/delivery/cod/").status_code == 401


def test_staff_are_limited_to_their_stores(staff_client, job):
    base = f"/api/delivery/shipments/{job.shipment_id}/"
    assert staff_client.get("/api/delivery/shipments/", {"scope": "all"}).json()["results"] == []
    assert staff_client.get("/api/delivery/partners/").json() == []
    for method, path in [
        ("get", base), ("post", base + "reassign/"), ("post", base + "unassign/"),
        ("post", base + "complete-without-otp/"), ("get", base + "proof/"),
        ("post", f"/api/delivery/cod/{job.pk}/handover/"),
    ]:  # fmt: skip
        res = getattr(staff_client, method)(path, {"partner_id": job.partner_id, "note": "x"}, format="json")
        assert res.status_code == 404, (path, res.status_code)
    job.refresh_from_db()
    assert job.status == A.ASSIGNED


def test_customers_cannot_use_staff_delivery_endpoints(auth_client, job):
    base = f"/api/delivery/shipments/{job.shipment_id}/"
    for method, path in [
        ("get", base), ("post", base + "reassign/"), ("post", base + "unassign/"),
        ("post", base + "complete-without-otp/"), ("get", "/api/delivery/partners/"),
        ("get", "/api/delivery/cod/"), ("post", f"/api/delivery/cod/{job.pk}/handover/"),
    ]:  # fmt: skip
        assert getattr(auth_client, method)(path, {}, format="json").status_code == 403, path


def test_staff_close_a_delivery_without_the_code(manager, job):
    base = f"/api/delivery/shipments/{job.shipment_id}/complete-without-otp/"
    early = manager.post(base, {"note": "x"}, format="json")
    assert early.status_code == 409 and error(early) == "invalid_delivery_state"
    advance(job, "out_for_delivery")
    assert manager.post(base, {}, format="json").status_code == 400
    body = {"note": "Phone dead, ID checked", "cod_collected": True, "cod_amount": "1200.00", "cod_method": "upi"}
    res = manager.post(base, body, format="json")
    assert res.status_code == 200, res.json()
    assert res.json()["status"] == "delivered" and res.json()["rider"]["completed_without_otp"] is True
    assert res.json()["cod"]["method"] == "upi" and res.json()["cod"]["handed_over"] is True


# --- Return pickups ------------------------------------------------------------------------------


@pytest.fixture
def approved_return(user, shop, job, admin_user):
    advance(job, "out_for_delivery")
    deliver_job(job)
    order = Order.objects.get(pk=job.order_id)
    item = order.items.get()
    ret = request_return(order, user=user, items=[{"order_item_id": item.id, "quantity": 1}], reason="defective")
    return approve_return(ret, actor=admin_user)


def test_return_pickup_from_assignment_to_the_store(manager, rider, auth_client, approved_return, shop, admin_user):
    ret = approved_return
    base = f"/api/returns/{ret.return_number}/"
    res = manager.post(base + "assign-pickup/", {"partner_id": shop["rider"].pk}, format="json")
    assert res.status_code == 201, res.json()
    assert res.json()["pickup"]["status"] == "assigned" and res.json()["pickup"]["rider_name"] == "Rider"
    twice = manager.post(base + "assign-pickup/", {"partner_id": shop["rider"].pk}, format="json")
    assert twice.status_code == 409 and error(twice) == "already_assigned"

    (row,) = rider.get("/api/delivery/assignments/", {"kind": "return_pickup"}).json()["results"]
    assert row["kind_label"] == "Return pickup from the customer" and row["return_number"] == ret.return_number
    assert row["amount_to_collect"] is None and row["cod"] is None
    assert row["pickup"]["name"] == "Asha Kumar" and row["drop"]["name"] == "Kothrud Store"  # the other way round
    assert row["items"] == [{"name": "Drill", "variant": "", "sku": shop["drill"].sku, "quantity": 1}]

    pickup_url = f"/api/delivery/assignments/{row['id']}/"
    rider.post(pickup_url + "accept/")
    assert rider.post(pickup_url + "start/", {}, format="json").status_code == 409
    collected = rider.post(pickup_url + "pickup/", {}, format="json").json()
    assert collected["status"] == "picked_up" and collected["next_actions"] == ["proof", "complete", "fail"]
    assert rider.post(pickup_url + "proof/", {"photo": photo()}, format="multipart").status_code == 200
    seen = auth_client.get(base).json()["pickup"]
    assert seen["status_label"] == "Collected from you, on the way to the store" and seen["rider_phone"]

    done = rider.post(pickup_url + "complete/", {}, format="json").json()  # no code, no cash for a return
    assert done["status"] == "delivered" and done["earning_amount"] == "41.20"
    ret.refresh_from_db()
    assert ret.status == "approved"  # the store still checks the goods and receives the return
    ret.order.refresh_from_db()
    assert ret.order.status == "return_requested"

    received = manager.post(base + "receive/", {"restock": True}, format="json")
    assert received.status_code == 200 and received.json()["pickup"]["status"] == "delivered"
    assert received.json()["pickup"]["rider_phone"] is None


def test_return_pickup_rules(manager, rider, approved_return, shop, user, admin_user):
    from apps.orders.returns import reject_return

    ret = approved_return
    base = f"/api/returns/{ret.return_number}/"
    assert manager.post(base + "assign-pickup/", {"partner_id": 999999}, format="json").status_code == 404
    off = create_partner(shop["store"], email="off@example.com", status="offline")
    res = manager.post(base + "assign-pickup/", {"partner_id": off.pk}, format="json")
    assert res.status_code == 409 and error(res) == "partner_unavailable"

    manager.post(base + "assign-pickup/", {"partner_id": shop["rider"].pk}, format="json")
    job = DeliveryAssignment.objects.get(kind="return_pickup")
    pickup_url = f"/api/delivery/assignments/{job.pk}/"
    rider.post(pickup_url + "accept/")
    failed = rider.post(pickup_url + "fail/", {"reason": "customer_unavailable"}, format="json").json()
    assert failed["status"] == "failed"
    ret.order.refresh_from_db()
    assert ret.order.status == "return_requested"  # a failed pickup doesn't touch the order

    manager.post(base + "assign-pickup/", {"partner_id": shop["rider"].pk}, format="json")
    second = DeliveryAssignment.objects.filter(kind="return_pickup").latest("id")
    reject_return(ret, actor=admin_user, note="Item was used")
    second.refresh_from_db()
    shop["rider"].refresh_from_db()
    assert second.status == A.CANCELLED and shop["rider"].status == "available"
    late = manager.post(base + "assign-pickup/", {"partner_id": shop["rider"].pk}, format="json")
    assert late.status_code == 409 and error(late) == "invalid_delivery_state"


def test_return_pickup_permissions(auth_client, staff_client, rider, approved_return, shop):
    base = f"/api/returns/{approved_return.return_number}/assign-pickup/"
    body = {"partner_id": shop["rider"].pk}
    assert auth_client.post(base, body, format="json").status_code == 403
    assert staff_client.post(base, body, format="json").status_code in (403, 404)  # another store's manager
    assert rider.post(base, body, format="json").status_code in (403, 404)
    assert not DeliveryAssignment.objects.filter(kind="return_pickup").exists()


# --- Django admin --------------------------------------------------------------------------------


@pytest.fixture
def admin_site():
    client = Client()
    client.force_login(get_user_model().objects.create_superuser(email="root@example.com", password="Passw0rd!x"))
    return client


def test_admin_shows_status_riders_cash_and_history(admin_site, rider, job, shop):
    advance(job, "out_for_delivery")
    code = delivery_code(job)
    rider.post(url(job, "proof"), {"photo": photo()}, format="multipart")
    deliver_job(job)
    job.refresh_from_db()
    pages = [
        reverse("admin:orders_ordershipment_changelist"),
        reverse("admin:orders_ordershipment_change", args=[job.shipment_id]),
        reverse("admin:delivery_deliveryassignment_changelist"),
        reverse("admin:delivery_deliveryassignment_change", args=[job.pk]),
        reverse("admin:delivery_deliverypartner_changelist"),
        reverse("admin:delivery_deliverypartner_change", args=[job.partner_id]),
        reverse("admin:orders_order_change", args=[job.order_id]),
    ]
    bodies = {}
    for page in pages:
        res = admin_site.get(page)
        assert res.status_code == 200, page
        bodies[page] = res.content.decode()
    job_page = bodies[pages[3]]
    assert "1200.00" in job_page and "Picked up" in job_page
    # Secrets and the photo's location never appear in the admin.
    for body in bodies.values():
        assert code not in body and job.otp_hash not in body and job.otp_nonce not in body
        assert job.proof_image.name not in body
    assert "₹1200.00" in bodies[pages[4]]  # cash the rider carries
    assert admin_site.get(reverse("admin:delivery_deliveryassignment_add")).status_code == 403
    assert admin_site.get(reverse("admin:orders_ordershipment_add")).status_code == 403

    admin_site.post(pages[2], {"action": "mark_cash_handed_over", "_selected_action": [job.pk]}, follow=True)
    job.refresh_from_db()
    assert job.cod_handed_over_at and job.cod_handed_over_to.email == "root@example.com"
    # Posting changes to a job does nothing.
    admin_site.post(pages[3], {"status": "assigned", "earning_amount": "999"})
    job.refresh_from_db()
    assert job.status == A.DELIVERED and job.earning_amount == Decimal("41.20")


def test_admin_assigns_reassigns_and_unassigns(admin_site, job, shop):
    second = create_partner(shop["store"], email="second@example.com")
    page = reverse("admin:orders_ordershipment_change", args=[job.shipment_id])
    res = admin_site.post(page, {"assign_to": second.pk, "reason": "Closer"}, follow=True)
    assert res.status_code == 200 and "Assigned to Rider second" in res.content.decode()
    job.refresh_from_db()
    assert job.status == A.CANCELLED
    assert DeliveryAssignment.objects.get(status="assigned").partner == second

    res = admin_site.post(page, {"unassign": "on"}, follow=True)
    assert "waiting for a delivery partner again" in res.content.decode()
    assert not DeliveryAssignment.objects.filter(status__in=DeliveryAssignment.ACTIVE_STATUSES).exists()

    res = admin_site.post(page, {"assign_to": second.pk}, follow=True)
    new = DeliveryAssignment.objects.get(status="assigned")
    advance(new, "picked_up")
    res = admin_site.post(page, {"assign_to": shop["rider"].pk}, follow=True)
    assert "already has the goods" in res.content.decode()
    new.refresh_from_db()
    assert new.status == A.PICKED_UP
