from decimal import Decimal

from apps.orders.pricing import PricedLine, calculate_totals
from apps.orders.state_machine import TRANSITIONS, can_transition


def _line(price: str, qty: int, gst: str = "18", mrp: str | None = None) -> PricedLine:
    return PricedLine(1, 1, 1, None, Decimal(price), Decimal(mrp or price), Decimal(gst), qty)


def test_totals_with_delivery_fee_below_threshold(settings):
    settings.DELIVERY_FEE = Decimal("40.00")
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("499.00")
    totals = calculate_totals([_line("118.00", 2)])
    assert totals.subtotal == Decimal("236.00")
    assert totals.tax_total == Decimal("36.00")  # 236 * 18/118
    assert totals.delivery_fee == Decimal("40.00")
    assert totals.grand_total == Decimal("276.00")


def test_discount_reduces_tax_pro_rata_and_can_remove_free_delivery(settings):
    settings.FREE_DELIVERY_MIN_ORDER = Decimal("499.00")
    settings.DELIVERY_FEE = Decimal("40.00")
    totals = calculate_totals([_line("590.00", 1)], discount=Decimal("118.00"))
    assert totals.tax_total == Decimal("72.00")  # (590-118) * 18/118
    assert totals.delivery_fee == Decimal("40.00")  # 472 after discount is below 499
    assert totals.grand_total == Decimal("512.00")


def test_discount_never_exceeds_subtotal():
    totals = calculate_totals([_line("100.00", 1)], discount=Decimal("500"))
    assert totals.discount_total == Decimal("100.00")
    assert totals.grand_total == Decimal("0.00")


def test_state_machine_has_no_exit_from_terminal_states():
    assert TRANSITIONS["cancelled"] == frozenset() and TRANSITIONS["returned"] == frozenset()
    assert can_transition("pending", "confirmed")
    assert not can_transition("pending", "delivered")
    assert not can_transition("picked_up", "cancelled")
