"""Cash-on-delivery eligibility (Phase 15). One function used by the checkout preview and by
`place_order`, so what the customer is shown is what ordering enforces.

COD is available when all of these hold:
1. Switched on shop-wide (`PaymentSettings.cod_enabled`).
2. The order total is at most `PaymentSettings.cod_max_order_value` (default ₹10,000; blank = no limit).
3. Every store shipping the order allows it (`Store.cod_enabled`).
4. Every delivery zone used allows it (`DeliveryZone.cod_enabled`).
The reason shown is the first rule that fails. Collection, handover and refunds of cash are the
Phase 8/10 flows and are not affected.
"""

from dataclasses import dataclass
from decimal import Decimal

from .models import PaymentSettings


@dataclass(frozen=True)
class CodDecision:
    available: bool
    reason_code: str = ""
    message: str = ""
    max_order_value: Decimal | None = None


def format_inr(amount: Decimal) -> str:
    """₹10,000 / ₹1,25,000 (Indian digit grouping; paise only when not whole)."""
    amount = Decimal(amount)
    whole = int(amount)
    paise = amount - whole
    digits = str(abs(whole))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    text = f"₹{'-' if whole < 0 else ''}{digits}"
    return text + (f".{int(paise * 100):02d}" if paise else "")


def cod_eligibility(*, grand_total: Decimal, plan=None, settings: PaymentSettings | None = None) -> CodDecision:
    """`plan` is the fulfilment plan (apps.delivery.fulfillment.Plan) or None before an address is chosen."""
    settings = settings or PaymentSettings.load()
    limit = settings.cod_max_order_value
    if not settings.cod_enabled:
        return CodDecision(False, "cod_disabled", "Cash on Delivery isn't available right now.", limit)
    if limit is not None and grand_total > limit:
        return CodDecision(
            False, "cod_limit", f"Cash on Delivery isn't available for orders above {format_inr(limit)}.", limit
        )
    for shipment in getattr(plan, "shipments", None) or []:
        if not shipment.store.cod_enabled:
            return CodDecision(
                False, "cod_store", f"Cash on Delivery isn't available from {shipment.store.name}.", limit
            )
        if shipment.zone is not None and not shipment.zone.cod_enabled:
            return CodDecision(False, "cod_zone", "Cash on Delivery isn't available at this address.", limit)
    return CodDecision(True, max_order_value=limit)
