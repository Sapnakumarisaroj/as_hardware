"""Phase 17 under real concurrency (threads with their own connections; see orders/tests/test_concurrency.py).

Invariants: the same credit is never spent twice, the balance never goes below zero, cashback is
credited once, expiry is written once, a cancellation gives credits back once."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from apps.carts.services import add_item
from apps.core.testing import create_address, create_product, create_store
from apps.loyalty import ledger
from apps.loyalty.models import CashbackRule, CreditAllocation, CreditEntry
from apps.orders.models import Order
from apps.orders.services import cancel_order_by_customer, place_order, transition_order
from apps.orders.tests.helpers import deliver
from apps.orders.tests.test_concurrency import _error_codes, _ok, run_concurrently
from apps.payments.models import PaymentSettings

pytestmark = pytest.mark.django_db(transaction=True)
D = Decimal
K, S = CreditEntry.Kind, CreditEntry.Status


@pytest.fixture
def drill():
    rules = PaymentSettings.load()
    rules.cod_max_order_value = None
    rules.save()
    _, variant = create_product(name="Drill", price="1000.00", mrp="1200.00", stock=50, store=create_store())
    return variant


def test_the_same_credit_is_never_spent_twice(user):
    ledger.grant(user, K.PROMO, D("100"), reference="test")
    orders = [
        Order.objects.create(
            order_number=f"T{i}", user=user, address_snapshot={}, payment_method="cod", subtotal=0, mrp_total=0,
            discount_total=0, delivery_fee=0, tax_total=0, grand_total=0,
        )
        for i in range(2)
    ]  # fmt: skip

    def spend(order):
        def call():
            with transaction.atomic():
                return ledger.redeem(user, order, D("80"))

        return call

    results = run_concurrently(spend(orders[0]), spend(orders[1]))
    assert len(_ok(results)) == 1 and _error_codes(results) == ["totals_changed"]
    assert ledger.balance(user) == D("20.00")
    assert sum(a.amount for a in CreditAllocation.objects.all()) == D("80.00")


def test_concurrent_checkouts_never_overspend(user, drill):
    ledger.grant(user, K.PROMO, D("150"), reference="test")
    address = create_address(user)
    add_item(user, drill.id, 1)

    def checkout():
        return place_order(user=user, address_id=address.id, payment_method="cod", use_credits=True)

    results = run_concurrently(checkout, checkout, checkout)
    placed = [value[0] for value in _ok(results)]
    assert len(placed) == 1  # the cart is used up by the first; the others find it empty
    assert placed[0].credit_discount == D("150.00")
    assert ledger.balance(user) == D("0.00")
    assert CreditEntry.objects.filter(kind=K.REDEMPTION).count() == 1


def test_cashback_is_credited_and_expired_once(user, staff_user, drill):
    CashbackRule.objects.create(name="10%", percent=D("10"), starts_at=timezone.now() - timedelta(days=1))
    add_item(user, drill.id, 2)
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod")
    order = deliver(order, staff_user)
    entry = CreditEntry.objects.get(order=order, kind=K.CASHBACK)
    later = entry.available_at + timedelta(minutes=1)

    results = run_concurrently(*[lambda: ledger.release_due(now=later)] * 3)
    assert sum(_ok(results)) == 1
    entry.refresh_from_db()
    assert entry.status == S.AVAILABLE and ledger.balance(user) == D("200.00")

    expired_at = entry.expires_at + timedelta(minutes=1)
    results = run_concurrently(*[lambda: ledger.expire_due(now=expired_at)] * 3)
    assert sum(_ok(results)) == 1
    assert CreditEntry.objects.filter(kind=K.EXPIRY).count() == 1 and ledger.balance(user) == D("0.00")


def test_concurrent_cancellations_give_credits_back_once(user, staff_user, drill):
    ledger.grant(user, K.PROMO, D("100"), reference="test")
    CashbackRule.objects.create(name="10%", percent=D("10"), starts_at=timezone.now() - timedelta(days=1))
    add_item(user, drill.id, 1)
    order, _ = place_order(user=user, address_id=create_address(user).id, payment_method="cod", use_credits=True)
    results = run_concurrently(
        lambda: cancel_order_by_customer(order, user=user, reason="No longer needed"),
        lambda: transition_order(order, "cancelled", actor=staff_user, note="Out of stock"),
    )
    assert len(_ok(results)) == 1
    assert CreditEntry.objects.filter(order=order, kind=K.RESTORE).count() == 1
    assert CreditEntry.objects.get(order=order, kind=K.CASHBACK).status == S.REVERSED
    assert ledger.balance(user) == D("100.00")
