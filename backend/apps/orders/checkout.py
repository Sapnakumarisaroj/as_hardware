"""Checkout validation and preview: the same rules `place_order` enforces, without writing.

`build_checkout()` re-reads the cart with current prices and stock, validates the address
and coupon, quotes delivery, and lists anything that blocks ordering. The frontend shows
this; it never computes money itself.

Delivery quoting (`quote_delivery`) is deliberately simple until the Phase 9 fulfilment
engine: it says whether one store can supply the whole cart, the fee, the free-delivery
threshold and whether that store offers fast delivery. It never invents an ETA.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from apps.accounts.models import Address
from apps.carts.services import CartSummary, summarize_cart
from apps.core.exceptions import ServiceError
from apps.core.money import ZERO, q
from apps.offers.engine import OfferResult
from apps.offers.models import Coupon
from apps.offers.services import get_valid_coupon
from apps.stores.models import Store

from .pricing import Totals, delivery_fee_for, price_lines

ETA_PENDING_MESSAGE = "Delivery estimate will be confirmed after your order is placed."


@dataclass
class DeliveryQuote:
    available: bool
    fee: Decimal
    free_delivery_min_order: Decimal
    amount_to_free_delivery: Decimal
    fast_delivery_possible: bool = False
    eta_minutes: int | None = None  # filled by the Phase 9 ETA engine; None = not promised
    store_name: str | None = None
    message: str = ETA_PENDING_MESSAGE


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

    @property
    def can_place_order(self) -> bool:
        return not self.blocking_issues


def find_fulfilment_store(requirements: dict[int, int]) -> Store | None:
    """First active fulfilment store holding every variant in the required quantity.
    (Distance/zone/ETA-based selection replaces this in Phase 9.)"""
    from collections import defaultdict

    from apps.inventory.models import Inventory

    if not requirements:
        return None
    rows = Inventory.objects.filter(
        variant_id__in=requirements.keys(),
        is_active=True,
        store__is_active=True,
        store__is_deleted=False,
        store__accepts_orders=True,
        store__kind__in=Store.FULFILLMENT_KINDS,
    ).values_list("store_id", "variant_id", "available_quantity")
    coverage: dict[int, set[int]] = defaultdict(set)
    for store_id, variant_id, available in rows:
        if available >= requirements[variant_id]:
            coverage[store_id].add(variant_id)
    needed = set(requirements)
    for store_id in sorted(coverage):
        if coverage[store_id] >= needed:
            return Store.objects.get(pk=store_id)
    return None


def quote_delivery(requirements: dict[int, int], amount_after_discount: Decimal) -> DeliveryQuote:
    from apps.delivery.models import DeliveryZone

    threshold = q(settings.FREE_DELIVERY_MIN_ORDER)
    fee = delivery_fee_for(amount_after_discount)
    to_free = q(max(threshold - amount_after_discount, ZERO)) if fee > 0 else ZERO
    store = find_fulfilment_store(requirements)
    if store is None:
        return DeliveryQuote(
            available=False,
            fee=fee,
            free_delivery_min_order=threshold,
            amount_to_free_delivery=to_free,
            message="These items can't be delivered together right now. Reduce quantities or remove items.",
        )
    fast = DeliveryZone.objects.filter(store=store, is_active=True, fast_delivery_enabled=True).exists()
    return DeliveryQuote(
        available=True,
        fee=fee,
        free_delivery_min_order=threshold,
        amount_to_free_delivery=to_free,
        fast_delivery_possible=fast,
        store_name=store.name,
    )


def build_checkout(user, *, address_id: int | None = None, coupon_code: str = "") -> CheckoutSummary:
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

    lines = cart.priced_lines
    pricing = price_lines(lines)  # automatic offers
    coupon, coupon_error = None, None
    if coupon_code.strip() and lines:
        try:
            coupon = get_valid_coupon(coupon_code, user)
            pricing = price_lines(lines, coupon=coupon)  # coupon on top of offers
        except ServiceError as exc:
            coupon = None
            coupon_error = {"code": exc.error_code, "message": str(exc.detail), "details": exc.details}
            issues.append({"code": "coupon_invalid", "message": str(exc.detail)})
    totals = pricing.totals
    discount = totals.coupon_discount

    requirements = {line.item.variant_id: line.item.quantity for line in cart.lines if line.in_stock}
    delivery = quote_delivery(requirements, totals.subtotal - totals.discount_total)
    if cart.lines and not cart.issues and not delivery.available:
        issues.append({"code": "not_deliverable", "message": delivery.message})

    return CheckoutSummary(
        cart=cart,
        totals=totals,
        address=address,
        coupon=coupon,
        coupon_discount=discount,
        coupon_error=coupon_error,
        delivery=delivery,
        blocking_issues=issues,
        offers=pricing.offers,
    )
