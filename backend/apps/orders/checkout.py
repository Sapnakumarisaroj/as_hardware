"""Checkout validation and preview: the same rules `place_order` enforces, without writing.

`build_checkout()` re-reads the cart with current prices and stock, validates the address and
coupon, plans fulfilment for the chosen address (apps.delivery.fulfillment: zones, store
selection, ETA, delivery fee rule) and lists anything that blocks ordering. The frontend shows
this; it never computes money or delivery times itself.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from apps.accounts.models import Address
from apps.carts.services import CartSummary, summarize_cart
from apps.core.exceptions import ServiceError
from apps.core.money import ZERO, q
from apps.delivery.fulfillment import FeeRule, Plan, plan_fulfillment
from apps.delivery.locations import resolve_location
from apps.loyalty.ledger import cashback_for
from apps.offers.engine import OfferResult
from apps.offers.models import Coupon
from apps.offers.services import get_valid_coupon
from apps.payments.cod_rules import CodDecision, cod_eligibility

from .pricing import Totals, paid_by_line, price_lines

# Orders placed before the Phase 9 ETA engine (no estimate stored) still use this wording.
ETA_PENDING_MESSAGE = "Delivery estimate will be confirmed after your order is placed."
CHOOSE_ADDRESS_MESSAGE = "Choose a delivery address to see when your order can arrive."


@dataclass
class DeliveryQuote:
    available: bool
    fee: Decimal
    free_delivery_min_order: Decimal
    amount_to_free_delivery: Decimal
    fast_delivery_possible: bool = False
    eta_minutes: int | None = None  # None = no address yet / not deliverable
    store_name: str | None = None
    message: str = CHOOSE_ADDRESS_MESSAGE
    delivery_type: str | None = None  # fast | standard
    label: str = ""
    estimated_delivery_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    prep_minutes: int | None = None
    distance_km: float | None = None
    fast_unavailable_reason: str = ""
    location_precision: str | None = None
    reason_code: str = ""
    shipments: list[dict] = field(default_factory=list)
    # Phase 15: why delivery is free ("Orders from ₹499", a rule or an offer), or which items count.
    free_delivery_reason: str = ""
    free_delivery_hint: str = ""


@dataclass
class CheckoutSummary:
    cart: CartSummary
    totals: Totals
    address: Address | None
    coupon: Coupon | None
    coupon_discount: Decimal
    coupon_error: dict | None
    delivery: DeliveryQuote
    blocking_issues: list[dict] = field(default_factory=list)
    offers: OfferResult = field(default_factory=OfferResult)
    plan: Plan | None = None
    cod: CodDecision | None = None  # Phase 15: is cash on delivery allowed for this order?
    credits: object | None = None  # Phase 17: loyalty.ledger.CreditQuote (available, cap, usable)
    use_credits: bool = False
    cashback: object | None = None  # loyalty.ledger.CashbackQuote: earned if this order is placed

    @property
    def can_place_order(self) -> bool:
        return not self.blocking_issues


def shipment_rows(plan: Plan) -> list[dict]:
    rows = []
    for index, shipment in enumerate(plan.shipments, start=1):
        e = shipment.estimate
        rows.append(
            {
                "sequence": index,
                "store_name": shipment.store.name,
                "store_area": shipment.store.area,
                "line_count": len(shipment.lines),
                "delivery_type": e.delivery_type if e else None,
                "eta_minutes": e.eta_minutes if e else None,
                "label": e.label if e else "",
                "distance_km": round(e.distance_km, 1) if e and e.distance_km is not None else None,
            }
        )
    return rows


def quote_from_plan(plan: Plan | None, totals: Totals, fee_rule: FeeRule | None) -> DeliveryQuote:
    """Delivery part of a quote. The fee and free-delivery progress come from the pricing engine
    (`totals`, priced with the same `fee_rule`), never from a separate calculation."""
    rule = fee_rule or FeeRule.default()
    fee = totals.delivery_fee
    to_free = q(max(totals.amount_to_free_delivery, ZERO)) if fee > 0 else ZERO
    threshold = totals.free_delivery_threshold if totals.free_delivery_threshold is not None else rule.free_min
    base = {
        "fee": fee,
        "free_delivery_min_order": threshold,
        "amount_to_free_delivery": to_free,
        "free_delivery_reason": totals.free_delivery_reason,
        "free_delivery_hint": totals.free_delivery_hint if fee > 0 else "",
    }
    if plan is None:
        return DeliveryQuote(available=False, **base, message=CHOOSE_ADDRESS_MESSAGE)
    if not plan.deliverable:
        return DeliveryQuote(available=False, **base, message=plan.message, reason_code=plan.reason_code,
                             location_precision=plan.location.precision if plan.location else None)  # fmt: skip
    latest = plan.latest
    if latest is None:  # stock-only plan (no address yet)
        return DeliveryQuote(
            available=True, **base, store_name=plan.primary.store.name, message=CHOOSE_ADDRESS_MESSAGE,
            shipments=shipment_rows(plan),
        )  # fmt: skip
    fast = plan.delivery_type == "fast"
    label = latest.label
    message = (
        f"⚡ Fast delivery · {label}"
        if fast
        else f"Standard delivery · {label}"
        + (f" (fast delivery unavailable: {plan.fast_unavailable_reason})" if plan.fast_unavailable_reason else "")
    )
    return DeliveryQuote(
        available=True,
        **base,
        fast_delivery_possible=fast,
        eta_minutes=latest.eta_minutes,
        store_name=plan.primary.store.name,
        message=message,
        delivery_type=plan.delivery_type,
        label=label,
        estimated_delivery_at=latest.delivery_at,
        window_start=latest.window_start,
        window_end=latest.window_end,
        prep_minutes=max(e.prep_minutes for e in plan.estimates),
        distance_km=round(latest.distance_km, 1) if latest.distance_km is not None else None,
        fast_unavailable_reason=plan.fast_unavailable_reason,
        location_precision=plan.location.precision,
        shipments=shipment_rows(plan),
    )


def build_checkout(
    user, *, address_id: int | None = None, coupon_code: str = "", use_credits: bool = False
) -> CheckoutSummary:
    cart = summarize_cart(user)
    issues: list[dict] = []

    if not cart.lines:
        issues.append({"code": "cart_empty", "message": "Your cart is empty."})
    for message in cart.issues:
        issues.append({"code": "cart_item_unavailable", "message": message})

    address = None
    if address_id:
        address = Address.objects.filter(pk=address_id, user=user).first()
        if address is None:
            issues.append({"code": "address_not_found", "message": "Choose one of your saved addresses."})
    else:
        issues.append({"code": "address_required", "message": "Add or choose a delivery address."})

    requirements = {line.item.variant_id: line.item.quantity for line in cart.lines if line.in_stock}
    plan = None
    if requirements:
        location = resolve_location(address=address) if address else None
        plan = plan_fulfillment(requirements, location)
    fee_rule = plan.fee_rule if plan and plan.deliverable and plan.location else None

    lines = cart.priced_lines
    pricing = price_lines(lines, fee_rule=fee_rule, user=user, use_credits=use_credits)  # automatic offers
    coupon, coupon_error = None, None
    if coupon_code.strip() and lines:
        try:
            coupon = get_valid_coupon(coupon_code, user)
            pricing = price_lines(lines, coupon=coupon, fee_rule=fee_rule, user=user, use_credits=use_credits)
        except ServiceError as exc:
            coupon = None
            coupon_error = {"code": exc.error_code, "message": str(exc.detail), "details": exc.details}
            issues.append({"code": "coupon_invalid", "message": str(exc.detail)})
    totals = pricing.totals

    delivery = quote_from_plan(plan, totals, fee_rule)
    if cart.lines and not cart.issues and plan is not None and not plan.deliverable:
        issues.append({"code": "not_deliverable", "message": plan.message})
    cod = cod_eligibility(grand_total=totals.grand_total, plan=plan if plan and plan.deliverable else None)
    cashback = cashback_for(user, lines, paid_by_line(lines, totals, pricing.offers.line_discounts)) if lines else None

    return CheckoutSummary(
        cart=cart,
        totals=totals,
        address=address,
        coupon=coupon,
        coupon_discount=totals.coupon_discount,
        coupon_error=coupon_error,
        delivery=delivery,
        blocking_issues=issues,
        offers=pricing.offers,
        plan=plan,
        cod=cod,
        credits=pricing.credits,
        use_credits=use_credits,
        cashback=cashback,
    )
