"""Money helpers. All amounts are `Decimal` in INR with 2 decimal places — never float."""

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")

MONEY_FIELD_KWARGS = {"max_digits": 12, "decimal_places": 2}


def q(amount) -> Decimal:
    """Quantize to paise using commercial rounding."""
    return Decimal(amount).quantize(_CENT, rounding=ROUND_HALF_UP)


def included_tax(gross: Decimal, rate_percent: Decimal) -> Decimal:
    """GST contained in a tax-inclusive price: gross * r / (100 + r)."""
    if not rate_percent:
        return ZERO
    return q(gross * rate_percent / (Decimal(100) + rate_percent))
