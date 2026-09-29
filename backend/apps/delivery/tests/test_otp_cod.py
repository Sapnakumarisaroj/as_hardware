"""Phase 10: the delivery code (OTP) and cash on delivery."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import ServiceError
from apps.core.models import AuditLog
from apps.core.testing import create_coupon, create_product
from apps.delivery import otp, workflow
from apps.delivery.cod import cash_by_partner, cash_in_hand
from apps.delivery.models import DeliveryAssignment
from apps.orders.shipments import shipment_amounts
from apps.payments.models import Payment

from .helpers import advance, assign, create_partner, deliver_job, delivery_code, packed_order, store_at, zone_for

pytestmark = pytest.mark.django_db
A = DeliveryAssignment.Status
CASH = {"collected": True, "amount": "1200.00", "method": "cash"}


def code_of(exc) -> str:
    return exc.value.error_code


def wrong(code: str) -> str:
    return str((int(code) + 1) % 1_000_000).zfill(6)


@pytest.fixture
def shop():
    store = store_at(0, riders=0)
    zone_for(store)
    _, drill = create_product(name="Drill", price="600.00", mrp="700.00", stock=10, store=store)
    return {"store": store, "drill": drill, "rider": create_partner(store)}


@pytest.fixture
def job(user, shop, admin_user):
    """A cash-on-delivery job (₹1,200) that is out for delivery."""
    order = packed_order(user, (shop["drill"], 2), actor=admin_user)
    return advance(assign(order.shipments.get(), shop["rider"], actor=admin_user), "out_for_delivery")


def complete(job, code, cod=CASH, **kwargs):
    return workflow.complete_delivery(job.pk, rider=job.partner.user, code=code, cod=cod, **kwargs)


# --- The code ------------------------------------------------------------------------------------


def test_code_is_issued_when_the_rider_leaves_and_is_never_stored(user, shop, admin_user, settings):
    settings.DELIVERY_OTP_TTL_MINUTES = 30
    order = packed_order(user, (shop["drill"], 1), actor=admin_user)
    job = advance(assign(order.shipments.get(), shop["rider"], actor=admin_user), "picked_up")
    assert otp.state(job) == "none" and otp.code_for_customer(job) is None and job.otp_nonce == ""

    before = timezone.now()
    job = advance(job, "out_for_delivery")
    code = otp.code_for_customer(job)
    assert otp.state(job) == "active" and len(code) == 6 and code.isdigit()
    assert before + timedelta(minutes=30) <= job.otp_expires_at <= timezone.now() + timedelta(minutes=30)
    assert otp.code_for_customer(DeliveryAssignment.objects.get(pk=job.pk)) == code  # stable while valid
    stored = [str(v) for v in DeliveryAssignment.objects.filter(pk=job.pk).values().get().values()]
    assert not any(code in value for value in stored)
    assert job.otp_hash and job.otp_hash != code and len(job.otp_hash) == 64


def test_codes_differ_between_deliveries_and_depend_on_the_server_secret(job, shop, user, admin_user, settings):
    from django.contrib.auth import get_user_model

    other_customer = get_user_model().objects.create_user("c2@example.com", "S3cure-pass!", full_name="C Two")
    order = packed_order(other_customer, (shop["drill"], 1), actor=admin_user)
    second = assign(order.shipments.get(), create_partner(shop["store"], email="r2@example.com"), actor=admin_user)
    second = advance(second, "out_for_delivery")
    assert {otp._derive(job.pk, job.otp_nonce), otp._derive(second.pk, job.otp_nonce)} != {delivery_code(job)}
    mine = delivery_code(job)
    settings.SECRET_KEY = "another-secret"
    assert delivery_code(job) != mine


def test_right_code_completes_the_delivery_once(job):
    code = delivery_code(job)
    done = complete(job, code)
    assert done.status == A.DELIVERED and done.otp_verified_at and otp.state(done) == "used"
    assert otp.code_for_customer(done) is None
    with pytest.raises(ServiceError) as exc:  # single use: the same code again
        complete(job, code)
    assert code_of(exc) == "invalid_delivery_state" and exc.value.status_code == 409
    assert otp.check(done, code) == (False, "otp_used", "This delivery code was already used.")
    assert DeliveryAssignment.objects.filter(status=A.DELIVERED).count() == 1


@pytest.mark.parametrize("typed", ["12 34-56", " 123456 "])
def test_spaces_and_dashes_in_the_typed_code_are_ignored(job, typed):
    code = delivery_code(job)
    pretty = f"{code[:3]} {code[3:]}" if typed.startswith("12") else f" {code} "
    assert complete(job, pretty).status == A.DELIVERED


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "abcdef", None])
def test_malformed_codes_are_wrong_codes(job, typed):
    with pytest.raises(ServiceError) as exc:
        complete(job, typed)
    assert code_of(exc) == "otp_invalid"
    job.refresh_from_db()
    assert job.status == A.OUT_FOR_DELIVERY and job.otp_attempts == 1


def test_wrong_codes_are_counted_and_then_lock_the_code(job, settings):
    settings.DELIVERY_OTP_MAX_ATTEMPTS = 3
    code = delivery_code(job)
    for attempt, left in ((1, "2 tries left"), (2, "1 try left")):
        with pytest.raises(ServiceError) as exc:
            complete(job, wrong(code))
        assert code_of(exc) == "otp_invalid" and exc.value.status_code == 400 and left in str(exc.value.detail)
        job.refresh_from_db()
        assert job.otp_attempts == attempt  # saved although the request failed
    with pytest.raises(ServiceError) as exc:
        complete(job, wrong(code))
    assert code_of(exc) == "otp_locked"
    job.refresh_from_db()
    assert otp.state(job) == "locked" and otp.code_for_customer(job) is None

    with pytest.raises(ServiceError) as exc:  # even the right code is refused now
        complete(job, code)
    assert code_of(exc) == "otp_locked"
    job.refresh_from_db()
    assert job.status == A.OUT_FOR_DELIVERY and job.cod_collected_at is None and job.otp_attempts == 3


def test_expired_code_is_refused(job, settings):
    code = delivery_code(job)
    DeliveryAssignment.objects.filter(pk=job.pk).update(otp_expires_at=timezone.now() - timedelta(seconds=1))
    job.refresh_from_db()
    assert otp.state(job) == "expired" and otp.code_for_customer(job) is None
    with pytest.raises(ServiceError) as exc:
        complete(job, code)
    assert code_of(exc) == "otp_expired"
    job.refresh_from_db()
    assert job.status == A.OUT_FOR_DELIVERY and job.otp_attempts == 0  # not a guess


def test_customer_gets_a_new_code_and_the_old_one_dies(job, user, settings):
    settings.DELIVERY_OTP_RESEND_SECONDS = 60
    old = delivery_code(job)
    with pytest.raises(ServiceError) as exc:
        workflow.new_delivery_code(job.order, 1, user=user)
    assert code_of(exc) == "otp_too_soon" and exc.value.status_code == 409
    assert delivery_code(job) == old

    DeliveryAssignment.objects.filter(pk=job.pk).update(
        otp_issued_at=timezone.now() - timedelta(seconds=61), otp_attempts=5
    )
    workflow.new_delivery_code(job.order, 1, user=user)
    new = delivery_code(job)
    job.refresh_from_db()
    assert new != old and otp.state(job) == "active" and job.otp_attempts == 0
    with pytest.raises(ServiceError) as exc:
        complete(job, old)
    assert code_of(exc) == "otp_invalid"
    assert complete(job, new).status == A.DELIVERED


def test_new_code_only_for_the_owner_and_only_while_out_for_delivery(job, user, other_user, shop, admin_user):
    with pytest.raises(ServiceError) as exc:
        workflow.new_delivery_code(job.order, 1, user=other_user)
    assert code_of(exc) == "not_found"
    with pytest.raises(ServiceError) as exc:
        workflow.new_delivery_code(job.order, 2, user=user)  # no such shipment
    assert code_of(exc) == "otp_not_needed"
    complete(job, delivery_code(job))
    with pytest.raises(ServiceError) as exc:
        workflow.new_delivery_code(job.order, 1, user=user)
    assert code_of(exc) == "otp_not_needed"


def test_a_failed_attempt_kills_the_code_and_the_next_attempt_gets_its_own(job, shop, admin_user):
    old = delivery_code(job)
    workflow.fail_delivery(job.pk, rider=job.partner.user, reason_code="customer_unavailable")
    job.refresh_from_db()
    assert otp.state(job) == "none" and job.otp_hash == ""
    second = assign(job.shipment, create_partner(shop["store"], email="b@example.com"), actor=admin_user)
    second = advance(second, "out_for_delivery")
    with pytest.raises(ServiceError) as exc:
        complete(second, old)
    assert code_of(exc) == "otp_invalid"
    assert complete(second, delivery_code(second)).status == A.DELIVERED


def test_photo_can_be_made_mandatory(job, settings):
    from .helpers import photo

    settings.DELIVERY_PROOF_REQUIRED = True
    code = delivery_code(job)
    with pytest.raises(ServiceError) as exc:
        complete(job, code)
    assert code_of(exc) == "proof_required"
    job.refresh_from_db()
    assert job.otp_attempts == 0
    workflow.upload_proof(job.pk, rider=job.partner.user, photo=photo())
    assert complete(job, code).status == A.DELIVERED


# --- Cash on delivery ----------------------------------------------------------------------------


def test_cash_is_collected_at_the_door_and_the_order_becomes_paid(job):
    order = job.order
    assert job.cod_amount_due == order.grand_total == Decimal("1200.00")
    done = complete(job, delivery_code(job))
    assert (done.cod_collected_amount, done.cod_method) == (Decimal("1200.00"), "cash")
    assert done.cod_collected_at and done.cod_handed_over_at is None
    assert done.cash_in_hand == Decimal("1200.00")
    order.refresh_from_db()
    payment = Payment.objects.get(order=order)
    assert order.payment_status == "paid" and payment.status == "captured" and payment.amount == Decimal("1200.00")


@pytest.mark.parametrize(
    ("cod", "error"),
    [
        (None, "cod_not_collected"),
        ({}, "cod_not_collected"),
        ({"collected": False, "amount": "1200.00"}, "cod_not_collected"),
        ({"collected": True}, "cod_amount_mismatch"),
        ({"collected": True, "amount": "1199.99"}, "cod_amount_mismatch"),
        ({"collected": True, "amount": "1.00"}, "cod_amount_mismatch"),
        ({"collected": True, "amount": "12000.00"}, "cod_amount_mismatch"),
        ({"collected": True, "amount": "1200.00", "method": "cheque"}, "cod_method_invalid"),
    ],
)
def test_delivery_is_not_completed_without_the_exact_amount(job, cod, error):
    code = delivery_code(job)
    with pytest.raises(ServiceError) as exc:
        complete(job, code, cod=cod)
    assert code_of(exc) == error and exc.value.status_code == 400
    job.refresh_from_db()
    job.order.refresh_from_db()
    assert job.status == A.OUT_FOR_DELIVERY and job.cod_collected_at is None and job.otp_verified_at is None
    assert job.order.status == "out_for_delivery" and job.order.payment_status == "pending"
    assert complete(job, code).status == A.DELIVERED  # the code was not used up by the refusal


def test_upi_needs_no_handover(job):
    done = complete(job, delivery_code(job), cod={**CASH, "method": "upi", "reference": "UPI123456"})
    assert done.cod_method == "upi" and done.cod_reference == "UPI123456"
    assert done.cod_handed_over_at and done.cash_in_hand == Decimal("0.00")
    assert cash_in_hand(done.partner) == Decimal("0.00")


def test_online_orders_need_no_cash(user, shop, admin_user):
    order = packed_order(user, (shop["drill"], 1), method="online", actor=admin_user)
    job = advance(assign(order.shipments.get(), shop["rider"], actor=admin_user), "out_for_delivery")
    assert job.cod_amount_due == Decimal("0.00")
    done = workflow.complete_delivery(job.pk, rider=job.partner.user, code=delivery_code(job))
    assert done.status == A.DELIVERED and done.cod_collected_at is None and done.cod_method == ""
    # Claiming to have collected money changes nothing either.
    order.refresh_from_db()
    assert order.payment_status == "paid" and Payment.objects.filter(order=order, status="captured").count() == 1


def test_cash_is_handed_over_to_the_store_once(job, admin_user, staff_user):
    done = complete(job, delivery_code(job))
    partner = done.partner
    assert cash_in_hand(partner) == Decimal("1200.00") and cash_by_partner([partner.pk]) == {
        partner.pk: Decimal("1200.00")
    }

    handed = workflow.hand_over_cash(done.pk, actor=staff_user, note="Counted, correct")
    assert handed.cod_handed_over_at and handed.cod_handed_over_to == staff_user
    assert handed.cod_handover_note == "Counted, correct" and handed.cash_in_hand == Decimal("0.00")
    assert cash_in_hand(partner) == Decimal("0.00") and cash_by_partner([partner.pk]) == {}
    log = AuditLog.objects.get(action="delivery.cod_handover")
    assert log.actor == staff_user and log.changes["amount"] == "1200.00"

    with pytest.raises(ServiceError) as exc:
        workflow.hand_over_cash(done.pk, actor=admin_user)
    assert code_of(exc) == "cod_already_handed_over"
    handed.refresh_from_db()
    assert handed.cod_handed_over_to == staff_user


def test_no_handover_without_collection(job, admin_user):
    with pytest.raises(ServiceError) as exc:
        workflow.hand_over_cash(job.pk, actor=admin_user)
    assert code_of(exc) == "cod_not_collected"


def test_cash_in_hand_adds_up_over_deliveries(user, other_user, shop, admin_user):
    rider = shop["rider"]
    total = Decimal("0.00")
    for customer, quantity in ((user, 1), (other_user, 3)):
        order = packed_order(customer, (shop["drill"], quantity), actor=admin_user)
        job = advance(assign(order.shipments.get(), rider, actor=admin_user), "out_for_delivery")
        deliver_job(job)
        total += order.grand_total
    assert total == Decimal("2400.00") and cash_in_hand(rider) == total


def test_each_shipment_collects_its_own_share(user, admin_user):
    """₹650 of goods from two stores, a ₹65 coupon and the delivery fee: the shares add up to
    what the customer owes, and the order is paid once both riders have delivered."""
    a, b = store_at(0, riders=0), store_at(1, riders=0)
    zone_for(a, radius="10", delivery_fee_override=Decimal("30"), free_delivery_min_order=Decimal("5000"))
    zone_for(b, radius="10", delivery_fee_override=Decimal("30"), free_delivery_min_order=Decimal("5000"))
    _, drill = create_product(name="Drill", price="333.33", mrp="400.00", stock=5, store=a)
    _, tape = create_product(name="Tape", price="158.34", mrp="200.00", stock=5, store=b)
    create_coupon("TEN", value=Decimal("10"))

    from apps.carts.services import add_item
    from apps.orders.services import place_order, transition_order

    from .helpers import address_at

    add_item(user, drill.id, 1)
    add_item(user, tape.id, 2)
    order, _ = place_order(user=user, address_id=address_at(user, 0.5).id, payment_method="cod", coupon_code="TEN")
    for status in ("processing", "packed"):
        order = transition_order(order, status, actor=admin_user)
    first, second = order.shipments.order_by("sequence")
    shares = shipment_amounts(order)
    assert sum(shares.values()) == order.grand_total == Decimal("615.01")
    assert all(share > 0 for share in shares.values())
    fee_carrier = shares[first.pk] - sum((i.line_total for i in first.items.all()), Decimal("0"))
    assert fee_carrier > Decimal("-40")  # the first shipment carries the fee, less its coupon share

    jobs = [
        assign(first, create_partner(first.store, email="a@example.com"), actor=admin_user),
        assign(second, create_partner(second.store, email="b@example.com"), actor=admin_user),
    ]
    assert [j.cod_amount_due for j in jobs] == [shares[first.pk], shares[second.pk]]
    advance(jobs[0], "out_for_delivery")
    with pytest.raises(ServiceError) as exc:  # the whole order's total is not this rider's amount
        workflow.complete_delivery(
            jobs[0].pk,
            rider=jobs[0].partner.user,
            code=delivery_code(jobs[0]),
            cod={"collected": True, "amount": order.grand_total, "method": "cash"},
        )
    assert code_of(exc) == "cod_amount_mismatch" and exc.value.details == {"amount_due": str(shares[first.pk])}
    deliver_job(jobs[0])
    order.refresh_from_db()
    assert order.payment_status == "pending"
    advance(jobs[1], "out_for_delivery")
    deliver_job(jobs[1])
    order.refresh_from_db()
    assert order.status == "delivered" and order.payment_status == "paid"
    collected = sum(DeliveryAssignment.objects.filter(order=order).values_list("cod_collected_amount", flat=True))
    assert collected == order.grand_total == Payment.objects.get(order=order).amount


def test_reassigned_job_carries_the_same_amount(user, shop, admin_user):
    from apps.delivery.assignment import reassign_shipment

    order = packed_order(user, (shop["drill"], 2), actor=admin_user)
    first = assign(order.shipments.get(), shop["rider"], actor=admin_user)
    second = reassign_shipment(
        order.shipments.get(), create_partner(shop["store"], email="b@example.com"), actor=admin_user
    )
    first.refresh_from_db()
    assert first.cod_amount_due == second.cod_amount_due == Decimal("1200.00")
    assert first.cod_collected_at is None and cash_in_hand(first.partner) == Decimal("0.00")
