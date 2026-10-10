"""Quote (RFQ) workflow.

requested → quoted (staff prices every line, sets validity) → accepted (customer) → ordered
(checkout through `orders.services.place_order(quote=...)`). Side exits: cancelled (customer, before
a quotation), declined (customer, after one), rejected (staff), expired (validity passed; job).

Staff may revise a quotation (quoted → quoted) until the customer accepts it. Prices are GST
inclusive like every catalogue price and can never exceed the variant's MRP. Nothing here sets a
total: checkout prices the quoted lines through the one pricing engine.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.carts.services import CartLineView, CartSummary
from apps.catalog.models import ProductVariant
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.money import q
from apps.inventory.services import total_available
from apps.orders.pricing import calculate_totals, line_from_quote_item, price_lines, tier_for

from .models import Quote, QuoteItem

MAX_LINES = 50
MAX_VALID_DAYS = 90
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class QuoteError(ServiceError):
    default_code = "quote_error"


class QuoteStateError(ConflictError):
    default_code = "quote_state"


def max_line_quantity() -> int:
    return int(getattr(settings, "QUOTE_MAX_LINE_QUANTITY", 10000))


def _number() -> str:
    for _ in range(10):
        number = f"RFQ{timezone.localdate():%y%m%d}" + "".join(secrets.choice(_ALPHABET) for _ in range(5))
        if not Quote.objects.filter(number=number).exists():
            return number
    raise QuoteError("Couldn't create a quote number. Please try again.")


def _notify(user_or_users, event: str, quote: Quote, **context) -> None:
    from apps.notifications.services import notify, notify_many

    base = {"quote_number": quote.number}
    payload = {"context": {**base, **context}, "data": {**base, "quote_id": quote.pk}, "key": f"{event}:{quote.pk}"}
    if isinstance(user_or_users, list):
        notify_many(user_or_users, event=event, **payload)
    else:
        notify(user_or_users, event=event, **payload)


def _staff() -> list:
    from apps.notifications.services import staff_for_stores

    return staff_for_stores([])  # no store yet: the administrators


# --- Customer ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestedLine:
    variant_id: int
    quantity: int
    note: str = ""


@transaction.atomic
def request_quote(user, lines: list[RequestedLine], *, note: str = "", address_id: int | None = None) -> Quote:
    if not lines:
        raise QuoteError("Add at least one product to request a quote.", code="quote_empty")
    if len(lines) > MAX_LINES:
        raise QuoteError(f"A quote can have at most {MAX_LINES} products.", code="quote_too_many_lines")
    merged: dict[int, RequestedLine] = {}
    for line in lines:
        if not 1 <= line.quantity <= max_line_quantity():
            raise QuoteError(f"Quantities must be between 1 and {max_line_quantity()}.", code="invalid_quantity")
        if line.variant_id in merged:
            prev = merged[line.variant_id]
            line = RequestedLine(line.variant_id, prev.quantity + line.quantity, prev.note or line.note)
        merged[line.variant_id] = line
    variants = {
        v.pk: v
        for v in ProductVariant.objects.filter(pk__in=merged, is_active=True)
        .select_related("product")
        .prefetch_related("price_tiers")
    }
    for variant_id in merged:
        variant = variants.get(variant_id)
        if variant is None or not variant.product.is_purchasable:
            raise QuoteError("One of the products is no longer available.", code="product_unavailable")

    address = None
    if address_id:
        address = user.addresses.filter(pk=address_id).first()
        if address is None:
            raise NotFoundError("Address not found.")
    profile = getattr(user, "profile", None)
    quote = Quote.objects.create(
        number=_number(),
        user=user,
        customer_note=note[:1000],
        address=address,
        buyer_type=profile.buyer_type if profile else "",
        business_name=(profile.business_name if profile else "") or (address.business_name if address else ""),
        gstin=(profile.gstin if profile else "") or (address.gstin if address else ""),
    )
    QuoteItem.objects.bulk_create(
        [
            QuoteItem(
                quote=quote,
                variant=variants[line.variant_id],
                quantity=line.quantity,
                customer_note=line.note[:255],
                list_unit_price=tier_for(variants[line.variant_id], line.quantity).unit_price,
                sort_order=index,
            )
            for index, line in enumerate(merged.values())
        ]
    )
    _notify(_staff(), "quote.requested", quote, customer=user.get_full_name(), lines=len(merged))
    return quote


def _own(user, quote_id: int, *, lock: bool = False) -> Quote:
    qs = Quote.objects.select_for_update() if lock else Quote.objects
    quote = qs.filter(pk=quote_id, user=user).first()
    if quote is None:
        raise NotFoundError("Quote not found.")
    return quote


def _expire_if_due(quote: Quote) -> bool:
    """Mark a quotation whose validity has ended as expired. Returns True when it did."""
    if quote.status in (Quote.Status.QUOTED, Quote.Status.ACCEPTED) and quote.is_expired:
        quote.status = Quote.Status.EXPIRED
        quote.closed_reason = "Validity ended"
        quote.save(update_fields=["status", "closed_reason", "updated_at"])
        return True
    return False


def accept_quote(user, quote_id: int) -> Quote:
    with transaction.atomic():
        quote = _own(user, quote_id, lock=True)
        if quote.status != Quote.Status.QUOTED:
            raise QuoteStateError("Only a quotation that is ready can be accepted.", code="quote_not_ready")
        expired = _expire_if_due(quote)
        if not expired:
            quote.status, quote.accepted_at = Quote.Status.ACCEPTED, timezone.now()
            quote.save(update_fields=["status", "accepted_at", "updated_at"])
    # Raised after the commit so the expiry is kept.
    if expired:
        raise QuoteStateError("This quotation has expired. Please request a new one.", code="quote_expired")
    _notify(_staff(), "quote.accepted", quote, customer=user.get_full_name())
    return quote


@transaction.atomic
def close_by_customer(user, quote_id: int, reason: str = "") -> Quote:
    """Cancel a request that has no quotation yet, or decline a quotation."""
    quote = _own(user, quote_id, lock=True)
    if quote.status == Quote.Status.REQUESTED:
        quote.status = Quote.Status.CANCELLED
    elif quote.status in (Quote.Status.QUOTED, Quote.Status.ACCEPTED):
        quote.status = Quote.Status.DECLINED
    else:
        raise QuoteStateError("This quote can't be closed any more.", code="quote_closed")
    quote.closed_reason = reason[:255]
    quote.save(update_fields=["status", "closed_reason", "updated_at"])
    return quote


# --- Staff ---------------------------------------------------------------------------------------


@transaction.atomic
def send_quotation(
    quote_id: int, *, actor, prices: dict[int, Decimal], valid_days: int, shop_note: str = "", request=None
) -> Quote:
    """Price every line (item id → unit price, GST inclusive) and send the quotation."""
    quote = Quote.objects.select_for_update().filter(pk=quote_id).first()
    if quote is None:
        raise NotFoundError("Quote not found.")
    if quote.status not in (Quote.Status.REQUESTED, Quote.Status.QUOTED):
        raise QuoteStateError("Only open requests can be quoted.", code="quote_closed")
    if not 1 <= valid_days <= MAX_VALID_DAYS:
        raise QuoteError(f"Validity must be 1 to {MAX_VALID_DAYS} days.", code="invalid_validity")
    items = list(quote.items.select_related("variant__product"))
    errors = {}
    for item in items:
        price = prices.get(item.pk)
        if price is None:
            errors[str(item.pk)] = "Enter a price for every line."
        elif price <= 0:
            errors[str(item.pk)] = "The price must be more than zero."
        elif price > item.variant.mrp:
            errors[str(item.pk)] = f"The price can't be above the MRP (₹{item.variant.mrp})."
    if unknown := set(prices) - {item.pk for item in items}:
        errors["unknown_lines"] = f"Not lines of this quote: {sorted(unknown)}"
    if errors:
        raise QuoteError("Check the quoted prices.", code="invalid_prices", details=errors)
    for item in items:
        item.quoted_unit_price = q(prices[item.pk])
    QuoteItem.objects.bulk_update(items, ["quoted_unit_price"])
    now = timezone.now()
    revised = quote.status == Quote.Status.QUOTED
    quote.status, quote.quoted_at, quote.quoted_by = Quote.Status.QUOTED, now, actor
    quote.valid_until = now + timedelta(days=valid_days)
    quote.shop_note = shop_note[:1000]
    quote.save(update_fields=["status", "quoted_at", "quoted_by", "valid_until", "shop_note", "updated_at"])
    record_audit(
        action="quote.revised" if revised else "quote.sent",
        actor=actor,
        target=quote,
        request=request,
        changes={"lines": {str(i.pk): str(i.quoted_unit_price) for i in items}, "valid_days": valid_days},
    )
    _notify(quote.user, "quote.ready", quote, valid_until=timezone.localtime(quote.valid_until).strftime("%d %b %Y"))
    return quote


@transaction.atomic
def reject_quote(quote_id: int, *, actor, reason: str, request=None) -> Quote:
    quote = Quote.objects.select_for_update().filter(pk=quote_id).first()
    if quote is None:
        raise NotFoundError("Quote not found.")
    if quote.status not in (Quote.Status.REQUESTED, Quote.Status.QUOTED):
        raise QuoteStateError("Only open requests can be rejected.", code="quote_closed")
    quote.status, quote.closed_reason = Quote.Status.REJECTED, reason[:255]
    quote.save(update_fields=["status", "closed_reason", "updated_at"])
    record_audit(action="quote.rejected", actor=actor, target=quote, request=request, changes={"reason": reason})
    _notify(quote.user, "quote.rejected", quote, reason=reason[:255])
    return quote


def expire_due(now=None) -> int:
    """Quotations whose validity has ended (job `quotes.expire`)."""
    now = now or timezone.now()
    count = 0
    for quote in Quote.objects.filter(
        status__in=[Quote.Status.QUOTED, Quote.Status.ACCEPTED], valid_until__lte=now
    ).select_related("user"):
        with transaction.atomic():
            updated = Quote.objects.filter(pk=quote.pk, status__in=[Quote.Status.QUOTED, Quote.Status.ACCEPTED]).update(
                status=Quote.Status.EXPIRED, closed_reason="Validity ended", updated_at=now
            )
            if updated:
                count += 1
                _notify(quote.user, "quote.expired", quote)
    return count


# --- Checkout ------------------------------------------------------------------------------------


class _QuoteLineView(CartLineView):
    """A quotation line shown like a cart line (the checkout page renders both the same way)."""

    @property
    def price_changed(self) -> bool:
        return False


def _checkout_items(quote: Quote) -> list[QuoteItem]:
    return list(
        quote.items.select_related("variant__product__brand").prefetch_related(
            "variant__product__images", "variant__price_tiers"
        )
    )


def summary_for_checkout(user, quote_id: int) -> tuple[Quote, CartSummary]:
    """The accepted quotation as a cart-shaped summary for the checkout preview (no writes)."""
    quote = Quote.objects.filter(pk=quote_id, user=user).first()
    if quote is None:
        raise NotFoundError("Quote not found.")
    issues = []
    if quote.status != Quote.Status.ACCEPTED:
        issues.append("Accept this quotation before checking out.")
    elif quote.is_expired:
        issues.append("This quotation has expired. Please request a new one.")
    lines = []
    for item in _checkout_items(quote):
        variant, product = item.variant, item.variant.product
        purchasable = variant.is_active and product.is_purchasable and item.quoted_unit_price is not None
        available = total_available(variant.id) if purchasable else 0
        view = _QuoteLineView(
            item=item,
            available_quantity=available,
            purchasable=purchasable,
            priced=line_from_quote_item(item) if purchasable else None,
        )
        if not purchasable:
            issues.append(f"{product.name} is no longer available.")
        elif not view.in_stock:
            issues.append(f"Only {available} unit(s) of {variant} available.")
        lines.append(view)
    summary = CartSummary(cart=quote, lines=lines, totals=calculate_totals([]), issues=issues)
    pricing = price_lines(summary.priced_lines, user=user, automatic_offers=False)
    summary.totals, summary.offers = pricing.totals, pricing.offers
    return quote, summary


def lock_for_checkout(quote: Quote | int, user) -> tuple[Quote, list[QuoteItem]]:
    """Called inside `place_order`'s transaction: the quote must be this customer's, accepted and
    still valid. Locks it so the same quotation can't be ordered twice."""
    from apps.orders.services import OrderError

    quote_id = quote.pk if isinstance(quote, Quote) else quote
    quote = Quote.objects.select_for_update().filter(pk=quote_id, user=user).first()
    if quote is None:
        raise NotFoundError("Quote not found.")
    if quote.status == Quote.Status.ORDERED:
        raise OrderError("This quotation has already been ordered.", code="quote_already_ordered")
    if quote.status != Quote.Status.ACCEPTED:
        raise OrderError("Accept this quotation before checking out.", code="quote_not_accepted")
    if quote.is_expired:
        raise OrderError("This quotation has expired. Please request a new one.", code="quote_expired")
    items = _checkout_items(quote)
    if any(item.quoted_unit_price is None for item in items):
        raise OrderError("This quotation is incomplete.", code="quote_incomplete")
    return quote, items


def mark_ordered(quote: Quote, order) -> None:
    quote.status, quote.order = Quote.Status.ORDERED, order
    quote.save(update_fields=["status", "order", "updated_at"])
