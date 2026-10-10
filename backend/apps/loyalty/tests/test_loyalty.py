"""Phase 17 loyalty credits and cashback: the ledger, spending (20 % cap, oldest expiry first), the cashback
lifecycle (pending → eligible → credited → expired / reversed), cancellations, returns with proportional
restore, referrals, the order snapshot and who may see or change what."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.carts.services import add_item
from apps.core.models import AuditLog
from apps.core.testing import create_address, create_category, create_product, create_store
from apps.loyalty import ledger
from apps.loyalty.models import CashbackRule, CreditEntry, LoyaltySettings, Referral, ReferralCode
from apps.orders.models import OrderStatus
from apps.orders.returns import approve_return, credit_shares, paid_amounts, receive_return, request_return
from apps.orders.services import cancel_order_by_customer, place_order
from apps.orders.tests.helpers import deliver
from apps.payments.models import PaymentSettings

pytestmark = pytest.mark.django_db
D = Decimal
K, S = CreditEntry.Kind, CreditEntry.Status
NOW = timezone.now


@pytest.fixture(autouse=True)
def _no_cod_limit():
    rules = PaymentSettings.load()
    rules.cod_max_order_value = None
    rules.save()


@pytest.fixture
def shop(staff_user):
    store = create_store()
    store.managers.add(staff_user)
    tools = create_category("Tools")
    _, drill = create_product(name="Drill", price="4000.00", mrp="4500.00", stock=50, store=store, category=tools)
    _, tape = create_product(name="Tape", price="500.00", mrp="600.00", stock=50, store=store, category=tools)
    _, cement = create_product(name="Cement", price="30000.00", mrp="31000.00", stock=50, store=store)
    return {"store": store, "tools": tools, "drill": drill, "tape": tape, "cement": cement}


def promo(user, amount, *, days=90, reference="test"):
    return ledger.grant(user, K.PROMO, D(amount), reference=reference, description="Test credit", expiry_days=days)


def order(user, *pairs, use_credits=False):
    for variant, quantity in pairs:
        add_item(user, variant.id, quantity)
    placed, _ = place_order(
        user=user, address_id=create_address(user).id, payment_method="cod", use_credits=use_credits
    )
    return placed


# --- Ledger -------------------------------------------------------------------------------------------


def test_balance_is_the_sum_of_counted_entries(user):
    assert ledger.balance(user) == D("0.00")
    promo(user, "100")
    pending = ledger.grant(user, K.CASHBACK, D("40"), reference="X", pending=True)
    assert ledger.balance(user) == D("100.00") and ledger.pending_total(user) == D("40.00")
    pending.status = S.REVERSED
    pending.save()
    assert ledger.balance(user) == D("100.00")


def test_entries_need_a_reference_and_the_right_sign(user):
    with pytest.raises(ledger.CreditError):
        ledger.grant(user, K.PROMO, D("10"), reference=" ")
    with pytest.raises(ledger.CreditError):
        ledger.grant(user, K.PROMO, D("0"), reference="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        CreditEntry.objects.create(user=user, kind=K.PROMO, status=S.AVAILABLE, amount=D("-5"), reference="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        CreditEntry.objects.create(user=user, kind=K.REDEMPTION, status=S.POSTED, amount=D("5"), reference="x")


def test_oldest_expiring_credit_is_used_first(user, shop):
    late = promo(user, "300", days=80)
    early = promo(user, "100", days=10)
    placed = order(user, (shop["drill"], 1), use_credits=True)  # 20 % of 4000 = 800 → uses 400 (all)
    assert placed.credit_discount == D("400.00")
    redemption = CreditEntry.objects.get(order=placed, kind=K.REDEMPTION)
    used = [(a.lot_id, a.amount) for a in redemption.allocations.order_by("pk")]
    assert used == [(early.pk, D("100.00")), (late.pk, D("300.00"))]
    assert ledger.balance(user) == D("0.00")


def test_credits_pay_at_most_twenty_percent(auth_client, user, shop):
    promo(user, "1500")
    add_item(user, shop["drill"].id, 1)
    add_item(user, shop["tape"].id, 2)  # goods 5000
    address = create_address(user)
    plain = auth_client.post("/api/checkout/preview/", {"address_id": address.id}, format="json").json()
    assert plain["credits"] == {
        "enabled": True,
        "available": "1500.00",
        "max_share_percent": "20.00",
        "max_usable": "1000.00",
        "usable": "1000.00",
        "use_credits": False,
        "applied": "0.00",
        "remaining_to_pay": plain["totals"]["grand_total"],
    }
    used = auth_client.post(
        "/api/checkout/preview/", {"address_id": address.id, "use_credits": True}, format="json"
    ).json()
    assert used["credits"]["applied"] == "1000.00"
    assert D(used["totals"]["grand_total"]) == D(plain["totals"]["grand_total"]) - 1000
    assert used["totals"]["credit_discount"] == "1000.00"
    assert D(used["totals"]["tax_total"]) < D(plain["totals"]["tax_total"])  # GST on what is paid
    created = auth_client.post(
        "/api/orders/",
        {
            "address_id": address.id,
            "payment_method": "cod",
            "use_credits": True,
            "expected_total": used["totals"]["grand_total"],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert created.json()["credit_discount"] == "1000.00"
    assert ledger.balance(user) == D("500.00")


def test_credits_are_used_only_when_chosen_and_never_change_free_delivery(user, shop, settings):
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("4000")
    promo(user, "500")
    placed = order(user, (shop["drill"], 1))
    assert placed.credit_discount == D("0.00") and ledger.balance(user) == D("500.00")
    with_credit = order(user, (shop["drill"], 1), use_credits=True)
    assert with_credit.credit_discount == D("500.00")
    assert with_credit.delivery_fee == placed.delivery_fee  # 4000 of goods still earns free delivery


def test_switched_off_credits_and_visitors(user, shop, api_client):
    promo(user, "500")
    rules = LoyaltySettings.load()
    rules.credits_enabled = False
    rules.save()
    placed = order(user, (shop["drill"], 1), use_credits=True)
    assert placed.credit_discount == D("0.00")
    assert api_client.post("/api/checkout/preview/", {}, format="json").status_code == 401


def test_changed_balance_between_preview_and_order_is_refused(auth_client, user, shop):
    lot = promo(user, "500")
    add_item(user, shop["drill"].id, 1)
    address = create_address(user)
    preview = auth_client.post(
        "/api/checkout/preview/", {"address_id": address.id, "use_credits": True}, format="json"
    ).json()
    CreditEntry.objects.filter(pk=lot.pk).update(expires_at=NOW() - timedelta(seconds=1))
    response = auth_client.post(
        "/api/orders/",
        {
            "address_id": address.id,
            "payment_method": "cod",
            "use_credits": True,
            "expected_total": preview["totals"]["grand_total"],
        },
        format="json",
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "totals_changed"
    assert not CreditEntry.objects.filter(kind=K.REDEMPTION).exists()


# --- Cashback lifecycle -----------------------------------------------------------------------------------


def rule(**kwargs):
    defaults = {"name": "2% on big orders", "percent": D("2"), "starts_at": NOW() - timedelta(days=1)}
    defaults.update(kwargs)
    return CashbackRule.objects.create(**defaults)


def test_cashback_lifecycle_pending_eligible_credited_expired(user, staff_user, shop):
    rule(min_order_value=D("50000"))
    small = order(user, (shop["drill"], 1))
    assert not CreditEntry.objects.filter(order=small).exists()  # below ₹50,000
    big = order(user, (shop["cement"], 2))  # 60,000
    entry = CreditEntry.objects.get(order=big, kind=K.CASHBACK)
    assert (entry.status, entry.amount) == (S.PENDING, D("1200.00"))
    assert big.loyalty_snapshot["cashback"]["amount"] == "1200.00"
    assert ledger.balance(user) == D("0.00") and ledger.pending_total(user) == D("1200.00")

    big = deliver(big, staff_user)
    entry.refresh_from_db()
    assert entry.status == S.ELIGIBLE
    assert entry.available_at == big.delivered_at + timedelta(days=7)
    assert ledger.release_due(now=entry.available_at - timedelta(minutes=1)) == 0
    assert ledger.balance(user) == D("0.00")  # not spendable inside the return window

    assert ledger.release_due(now=entry.available_at + timedelta(minutes=1)) == 1
    assert ledger.release_due(now=entry.available_at + timedelta(minutes=2)) == 0  # never twice
    entry.refresh_from_db()
    assert entry.status == S.AVAILABLE and ledger.balance(user) == D("1200.00")

    assert ledger.expire_due(now=entry.expires_at + timedelta(minutes=1)) == 1
    assert ledger.expire_due(now=entry.expires_at + timedelta(minutes=2)) == 0
    entry.refresh_from_db()
    assert entry.status == S.EXPIRED and ledger.balance(user) == D("0.00")
    expiry = CreditEntry.objects.get(kind=K.EXPIRY, user=user)
    assert expiry.amount == D("-1200.00")


def test_partly_used_credit_expires_only_the_rest(user, shop):
    lot = promo(user, "1000")
    order(user, (shop["drill"], 1), use_credits=True)  # uses 800
    ledger.expire_due(now=lot.expires_at + timedelta(seconds=1))
    assert CreditEntry.objects.get(kind=K.EXPIRY).amount == D("-200.00")
    assert ledger.balance(user) == D("0.00")


def test_fixed_first_order_and_category_rules(user, other_user, staff_user, shop):
    rule(
        name="₹100 on first order",
        reward_type="fixed",
        percent=None,
        fixed_amount=D("100"),
        first_order_only=True,
        priority=1,
    )
    targeted = rule(name="5% on tools", percent=D("5"), priority=2)
    targeted.categories.set([shop["tools"]])
    first = order(user, (shop["tape"], 1))
    assert CreditEntry.objects.get(order=first).amount == D("100.00")  # first-order rule wins (priority)
    second = order(user, (shop["tape"], 2))
    assert CreditEntry.objects.get(order=second).amount == D("50.00")  # 5 % of 1000
    third = order(user, (shop["cement"], 1))
    assert not CreditEntry.objects.filter(order=third).exists()  # cement is not a tool


def test_cashback_is_on_what_is_paid_after_credits(user, shop):
    rule(percent=D("10"))
    promo(user, "800")
    placed = order(user, (shop["drill"], 1), use_credits=True)
    assert CreditEntry.objects.get(order=placed, kind=K.CASHBACK).amount == D("320.00")  # 10 % of 3200


def test_cancelled_order_reverses_cashback_and_gives_credits_back(user, shop):
    rule(percent=D("10"))
    lot = promo(user, "500", days=30)
    placed = order(user, (shop["drill"], 1), use_credits=True)
    assert ledger.balance(user) == D("0.00")
    cancel_order_by_customer(placed, user=user, reason="Changed my mind")
    cashback = CreditEntry.objects.get(order=placed, kind=K.CASHBACK)
    assert cashback.status == S.REVERSED
    restored = CreditEntry.objects.get(order=placed, kind=K.RESTORE)
    assert restored.amount == D("500.00") and restored.expires_at == lot.expires_at and restored.source_id == lot.pk
    assert ledger.balance(user) == D("500.00")
    # Nothing is reversed or restored twice.
    ledger.on_order_cancelled(placed)
    assert CreditEntry.objects.filter(order=placed, kind=K.RESTORE).count() == 1


def test_credits_whose_expiry_passed_are_not_given_back(user, shop):
    lot = promo(user, "500", days=30)
    placed = order(user, (shop["drill"], 1), use_credits=True)
    CreditEntry.objects.filter(pk=lot.pk).update(expires_at=NOW() - timedelta(minutes=1))
    cancel_order_by_customer(placed, user=user, reason="Too late")
    assert not CreditEntry.objects.filter(order=placed, kind=K.RESTORE).exists()
    assert ledger.balance(user) == D("0.00")


# --- Returns -----------------------------------------------------------------------------------------------


def test_partial_return_restores_credits_and_shrinks_cashback(user, staff_user, shop):
    rule(percent=D("10"))
    lot = promo(user, "1000", days=60)
    placed = order(user, (shop["drill"], 1), (shop["tape"], 2), use_credits=True)  # goods 5000, credits 1000
    placed = deliver(placed, staff_user)
    items = {i.sku: i for i in placed.items.all()}
    shares = credit_shares(placed)
    assert sum(shares.values()) == D("1000.00")
    paid = paid_amounts(placed)
    assert sum(paid.values()) == placed.grand_total - placed.delivery_fee  # credits are not money

    cashback = CreditEntry.objects.get(order=placed, kind=K.CASHBACK)
    assert cashback.amount == D("400.00") and cashback.status == S.ELIGIBLE  # 10 % of 4000 paid
    drill = items[shop["drill"].sku]
    ret = request_return(placed, user=user, items=[{"order_item_id": drill.id, "quantity": 1}], reason="damaged")
    assert ret.refund_amount == paid[drill.id] == D("3200.00")  # 4000 − its 800 credit share
    approve_return(ret, actor=staff_user)
    receive_return(ret, actor=staff_user)

    restored = CreditEntry.objects.get(order=placed, kind=K.RESTORE)
    assert restored.amount == D("800.00") and restored.expires_at == lot.expires_at
    cashback.refresh_from_db()
    assert cashback.status == S.REVERSED
    replacement = CreditEntry.objects.get(order=placed, kind=K.CASHBACK, source=cashback)
    assert replacement.amount == D("80.00") and replacement.status == S.ELIGIBLE  # 400 × 800/4000
    assert replacement.available_at == cashback.available_at
    assert ledger.balance(user) == D("800.00")


def test_two_partial_returns_shrink_cashback_step_by_step(user, staff_user, shop):
    rule(percent=D("10"))
    placed = deliver(order(user, (shop["tape"], 4)), staff_user)  # paid 2000 → cashback 200
    item = placed.items.get()
    for expected in (D("150.00"), D("100.00")):
        ret = request_return(placed, user=user, items=[{"order_item_id": item.id, "quantity": 1}], reason="damaged")
        approve_return(ret, actor=staff_user)
        receive_return(ret, actor=staff_user)
        live = CreditEntry.objects.get(order=placed, kind=K.CASHBACK, status__in=CreditEntry.WAITING)
        assert live.amount == expected
    assert CreditEntry.objects.filter(order=placed, kind=K.CASHBACK, status=S.REVERSED).count() == 2


def test_full_return_reverses_all_cashback(user, staff_user, shop):
    rule(percent=D("10"))
    placed = deliver(order(user, (shop["tape"], 2)), staff_user)
    item = placed.items.get()
    ret = request_return(placed, user=user, items=[{"order_item_id": item.id, "quantity": 2}], reason="damaged")
    approve_return(ret, actor=staff_user)
    receive_return(ret, actor=staff_user)
    placed.refresh_from_db()
    assert placed.status == OrderStatus.RETURNED
    assert not CreditEntry.objects.filter(order=placed, status__in=CreditEntry.WAITING).exists()
    assert ledger.release_due(now=NOW() + timedelta(days=30)) == 0


def test_cashback_waits_while_a_return_is_open(user, staff_user, shop):
    rule(percent=D("10"))
    placed = deliver(order(user, (shop["tape"], 2)), staff_user)
    item = placed.items.get()
    request_return(placed, user=user, items=[{"order_item_id": item.id, "quantity": 1}], reason="damaged")
    assert ledger.release_due(now=NOW() + timedelta(days=30)) == 0


def test_order_snapshot_keeps_old_rules(user, staff_user, shop):
    promo(user, "1000")
    placed = order(user, (shop["drill"], 1), use_credits=True)
    rules = LoyaltySettings.load()
    rules.max_order_share = D("50")
    rules.save()
    assert placed.loyalty_snapshot["max_order_share"] == "20.00"
    placed = deliver(placed, staff_user)
    assert sum(credit_shares(placed).values()) == D("800.00")  # from the order, not today's rules


# --- Referrals ------------------------------------------------------------------------------------------------


def test_referral_rules_against_abuse(user, other_user, shop):
    code = ReferralCode.for_user(other_user).code
    with pytest.raises(ledger.CreditError, match="own"):
        ledger.claim_referral(other_user, code)
    with pytest.raises(ledger.CreditError, match="isn't valid"):
        ledger.claim_referral(user, "NOPE1234")
    ledger.claim_referral(user, code.lower())
    with pytest.raises(ledger.CreditError, match="already"):
        ledger.claim_referral(user, code)
    newcomer = get_user_model().objects.create_user("late@example.com", "S3cure-pass!", full_name="Late")
    order(newcomer, (shop["tape"], 1))
    with pytest.raises(ledger.CreditError, match="new customers"):
        ledger.claim_referral(newcomer, code)


def test_referral_rewards_follow_the_first_delivered_order(user, other_user, staff_user, shop):
    rules = LoyaltySettings.load()
    rules.referral_reward, rules.referee_reward = D("150"), D("50")
    rules.save()
    ledger.claim_referral(user, ReferralCode.for_user(other_user).code)
    first = deliver(order(user, (shop["tape"], 1)), staff_user)
    referral = Referral.objects.get(referee=user)
    assert referral.status == Referral.Status.REWARDED and referral.rewarded_order == first
    rewards = CreditEntry.objects.filter(kind=K.REFERRAL)
    assert sorted((e.user_id, e.amount, e.status) for e in rewards) == sorted(
        [(other_user.pk, D("150.00"), S.ELIGIBLE), (user.pk, D("50.00"), S.ELIGIBLE)]
    )
    deliver(order(user, (shop["tape"], 1)), staff_user)
    assert CreditEntry.objects.filter(kind=K.REFERRAL).count() == 2  # once only
    ledger.release_due(now=first.delivered_at + timedelta(days=8))
    assert ledger.balance(other_user) == D("150.00")


def test_referral_without_rewards_records_no_money(user, other_user, staff_user, shop):
    ledger.claim_referral(user, ReferralCode.for_user(other_user).code)
    deliver(order(user, (shop["tape"], 1)), staff_user)
    assert Referral.objects.get(referee=user).status == Referral.Status.NO_REWARD
    assert not CreditEntry.objects.filter(kind=K.REFERRAL).exists()


# --- Welcome reward ---------------------------------------------------------------------------------------------


def welcome_on(amount="75"):
    rules = LoyaltySettings.load()
    rules.welcome_reward = D(amount)
    rules.save()


def welcomes(user):
    return CreditEntry.objects.filter(user=user, kind=K.PROMO, reference__startswith=ledger.WELCOME_PREFIX)


def test_welcome_reward_once_on_the_first_delivered_order_on_cashback_terms(user, staff_user, shop):
    welcome_on()
    first = order(user, (shop["tape"], 1))
    second = order(user, (shop["tape"], 1))
    assert not welcomes(user).exists()  # nothing at placement
    first = deliver(first, staff_user)
    entry = welcomes(user).get()
    assert (entry.amount, entry.status, entry.order) == (D("75.00"), S.ELIGIBLE, first)
    assert entry.reference == f"welcome:{first.order_number}"
    assert entry.available_at == first.delivered_at + timedelta(days=7) and ledger.balance(user) == D("0.00")
    deliver(second, staff_user)
    ledger.on_order_delivered(first)  # a repeated hook changes nothing
    assert welcomes(user).count() == 1
    ledger.release_due(now=entry.available_at + timedelta(minutes=1))
    entry.refresh_from_db()
    assert entry.status == S.AVAILABLE and ledger.balance(user) == D("75.00")
    assert entry.expires_at == entry.available_at + timedelta(minutes=1) + timedelta(days=90)


def test_no_welcome_reward_when_off_or_not_the_first_delivered_order(user, other_user, staff_user, shop):
    deliver(order(user, (shop["tape"], 1)), staff_user)  # reward off: 0
    assert not CreditEntry.objects.filter(user=user).exists()
    welcome_on()
    deliver(order(user, (shop["tape"], 1)), staff_user)  # second delivered order: no welcome
    assert not welcomes(user).exists()
    cancelled = order(other_user, (shop["tape"], 1))
    cancel_order_by_customer(cancelled, user=other_user, reason="Changed my mind")
    assert not welcomes(other_user).exists()  # cancelled orders are never delivered


def test_full_return_reverses_the_welcome_reward_partial_keeps_it(user, other_user, staff_user, shop):
    welcome_on()
    placed = deliver(order(user, (shop["tape"], 2)), staff_user)
    item = placed.items.get()
    ret = request_return(placed, user=user, items=[{"order_item_id": item.id, "quantity": 2}], reason="damaged")
    approve_return(ret, actor=staff_user)
    receive_return(ret, actor=staff_user)
    assert welcomes(user).get().status == S.REVERSED
    deliver(order(user, (shop["tape"], 1)), staff_user)
    assert welcomes(user).count() == 1  # once per customer, ever
    assert ledger.release_due(now=NOW() + timedelta(days=30)) == 0 and ledger.balance(user) == D("0.00")

    kept = deliver(order(other_user, (shop["tape"], 2)), staff_user)
    item = kept.items.get()
    ret = request_return(kept, user=other_user, items=[{"order_item_id": item.id, "quantity": 1}], reason="damaged")
    approve_return(ret, actor=staff_user)
    receive_return(ret, actor=staff_user)
    entry = welcomes(other_user).get()
    assert (entry.status, entry.amount) == (S.ELIGIBLE, D("75.00"))


def test_welcome_reward_in_wallet_and_ledger(auth_client, user, staff_user, shop):
    assert auth_client.get("/api/loyalty/wallet/").json()["welcome"] is None  # off
    welcome_on("50")
    wallet = auth_client.get("/api/loyalty/wallet/").json()
    assert wallet["welcome"]["status"] == "offer" and wallet["rules"]["welcome_reward"] == "50.00"
    placed = deliver(order(user, (shop["tape"], 1)), staff_user)
    wallet = auth_client.get("/api/loyalty/wallet/").json()
    assert wallet["welcome"]["status"] == "eligible" and wallet["welcome"]["order_number"] == placed.order_number
    rows = auth_client.get("/api/loyalty/ledger/").json()["results"]
    assert [r["kind_label"] for r in rows] == ["Welcome reward"]


def test_wallet_referral_summary_comes_from_referrals_and_the_ledger(auth_client, user, other_user, staff_user, shop):
    rules = LoyaltySettings.load()
    rules.referral_reward, rules.referee_reward = D("150"), D("50")
    rules.save()
    code = ReferralCode.for_user(user).code
    ledger.claim_referral(other_user, code)
    late = get_user_model().objects.create_user("friend2@example.com", "S3cure-pass!", full_name="Friend")
    ledger.claim_referral(late, code)
    referral = auth_client.get("/api/loyalty/wallet/").json()["referral"]
    assert (referral["code"], referral["joined"], referral["waiting"], referral["rewarded"]) == (code, 2, 2, 0)
    assert referral["credited"] == "0.00" and referral["pending"] == "0.00"
    friend_order = deliver(order(other_user, (shop["tape"], 1)), staff_user)
    referral = auth_client.get("/api/loyalty/wallet/").json()["referral"]
    assert (referral["joined"], referral["waiting"], referral["rewarded"]) == (2, 1, 1)
    assert referral["pending"] == "150.00" and referral["credited"] == "0.00"
    ledger.release_due(now=friend_order.delivered_at + timedelta(days=8))
    referral = auth_client.get("/api/loyalty/wallet/").json()["referral"]
    assert referral["pending"] == "0.00" and referral["credited"] == "150.00"


def test_admin_welcome_reward_setting(admin_client):
    assert admin_client.get("/api/admin/loyalty/settings/").json()["welcome_reward"] == "0.00"  # off by default
    bad = admin_client.patch("/api/admin/loyalty/settings/", {"welcome_reward": "-1"}, format="json")
    assert bad.status_code == 400 and "welcome_reward" in str(bad.json())
    ok = admin_client.patch("/api/admin/loyalty/settings/", {"welcome_reward": "100"}, format="json")
    assert ok.status_code == 200 and ok.json()["welcome_reward"] == "100.00"
    assert LoyaltySettings.load().welcome_reward == D("100.00")


# --- API and permissions ------------------------------------------------------------------------------------------


def test_wallet_and_ledger_show_only_my_entries(auth_client, user, other_user, shop):
    promo(user, "300")
    promo(other_user, "999")
    order(user, (shop["drill"], 1), use_credits=True)
    wallet = auth_client.get("/api/loyalty/wallet/").json()
    assert wallet["balance"] == "0.00" and wallet["used"] == "300.00" and wallet["earned"] == "300.00"
    assert wallet["rules"]["max_order_share"] == "20.00" and wallet["rules"]["never_cash"] is True
    assert len(wallet["referral"]["code"]) == 8
    rows = auth_client.get("/api/loyalty/ledger/").json()["results"]
    assert {r["kind"] for r in rows} == {"promo", "redemption"} and all(r["amount"] != "999.00" for r in rows)
    other_entry = CreditEntry.objects.get(user=other_user)
    assert auth_client.get(f"/api/loyalty/ledger/{other_entry.pk}/").status_code == 404


def test_customers_cannot_change_credits(auth_client, api_client, user):
    entry = promo(user, "100")
    for method, url, body in [
        ("post", "/api/loyalty/ledger/", {"amount": "1000"}),
        ("patch", f"/api/loyalty/ledger/{entry.pk}/", {"amount": "1000", "expires_at": "2099-01-01T00:00:00Z"}),
        ("delete", f"/api/loyalty/ledger/{entry.pk}/", None),
    ]:
        assert getattr(auth_client, method)(url, body, format="json").status_code == 405
    for url in ("/api/admin/loyalty/settings/", "/api/admin/loyalty/ledger/", "/api/admin/loyalty/cashback-rules/"):
        assert auth_client.get(url).status_code == 403
        assert api_client.get(url).status_code == 401
    assert (
        auth_client.post(
            "/api/admin/loyalty/promo-credits/", {"user": user.pk, "amount": "500", "reason": "x"}, format="json"
        ).status_code
        == 403
    )
    assert api_client.get("/api/loyalty/wallet/").status_code == 401
    entry.refresh_from_db()
    assert entry.amount == D("100.00") and ledger.balance(user) == D("100.00")


def test_store_managers_cannot_open_loyalty_admin(staff_client):
    assert staff_client.get("/api/admin/loyalty/settings/").status_code == 403
    assert staff_client.get("/api/admin/loyalty/ledger/").status_code == 403


def test_admin_promo_credit_is_a_ledger_entry_with_audit(admin_client, admin_user, user):
    created = admin_client.post(
        "/api/admin/loyalty/promo-credits/",
        {"user": user.pk, "amount": "250", "reason": "Sorry for the delay"},
        format="json",
    )
    assert created.status_code == 201
    entry = CreditEntry.objects.get(user=user)
    assert (entry.kind, entry.status, entry.amount, entry.created_by) == (K.PROMO, S.AVAILABLE, D("250.00"), admin_user)
    assert entry.description == "Sorry for the delay" and entry.reference == f"admin:{admin_user.pk}"
    assert AuditLog.objects.filter(action="loyalty.promo_credit").exists()
    assert (
        admin_client.post(
            "/api/admin/loyalty/promo-credits/", {"user": user.pk, "amount": "0", "reason": "x"}, format="json"
        ).status_code
        == 400
    )
    assert (
        admin_client.post(
            "/api/admin/loyalty/promo-credits/", {"user": admin_user.pk, "amount": "5", "reason": "x"}, format="json"
        ).status_code
        == 404
    )
    ledger_rows = admin_client.get("/api/admin/loyalty/ledger/", {"user": user.pk}).json()["results"]
    assert ledger_rows[0]["customer"]["email"] == user.email
    wallet = admin_client.get(f"/api/admin/loyalty/customers/{user.pk}/").json()
    assert wallet["balance"] == "250.00"


def test_admin_settings_and_rules(admin_client):
    assert (
        admin_client.patch("/api/admin/loyalty/settings/", {"max_order_share": "120"}, format="json").status_code == 400
    )
    ok = admin_client.patch("/api/admin/loyalty/settings/", {"max_order_share": "15", "expiry_days": 60}, format="json")
    assert ok.status_code == 200 and ok.json()["max_order_share"] == "15.00"
    assert AuditLog.objects.filter(action="loyalty_settings.update").exists()
    missing = admin_client.post(
        "/api/admin/loyalty/cashback-rules/",
        {"name": "Bad", "reward_type": "fixed", "starts_at": NOW().isoformat()},
        format="json",
    )
    assert missing.status_code == 400 and "fixed_amount" in str(missing.json())
    created = admin_client.post(
        "/api/admin/loyalty/cashback-rules/",
        {"name": "2% above ₹50,000", "percent": "2", "min_order_value": "50000", "starts_at": NOW().isoformat()},
        format="json",
    )
    assert (
        created.status_code == 201 and created.json()["summary"] == "2% cashback" and created.json()["state"] == "live"
    )


def test_order_detail_shows_credits_and_cashback(auth_client, user, shop):
    rule(percent=D("10"))
    promo(user, "200")
    placed = order(user, (shop["drill"], 1), use_credits=True)
    data = auth_client.get(f"/api/orders/{placed.order_number}/").json()
    assert data["credit_discount"] == "200.00"
    assert data["loyalty"]["earned"][0]["amount"] == "380.00" and data["loyalty"]["earned"][0]["status"] == "pending"


def test_referral_claim_api(auth_client, other_user):
    code = ReferralCode.for_user(other_user).code
    assert auth_client.post("/api/loyalty/referral/", {"code": code}, format="json").status_code == 201
    again = auth_client.post("/api/loyalty/referral/", {"code": code}, format="json")
    assert again.status_code == 400 and again.json()["error"]["code"] == "referral_already_used"
