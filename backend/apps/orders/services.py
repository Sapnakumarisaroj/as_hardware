"""Order workflows: placement from the cart, status transitions, cancellation.

Everything runs inside a transaction: if any step fails (stock, coupon, payment intent),
nothing is written.
"""

import secrets
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import Address
from apps.carts.models import Cart, CartItem
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.money import ZERO, q
from apps.delivery.fulfillment import Plan, plan_fulfillment
from apps.delivery.locations import resolve_location
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import InsufficientStock, apply_movement, total_available
from apps.loyalty.ledger import cashback_for, on_order_cancelled, on_order_delivered, record_cashback
from apps.loyalty.ledger import redeem as redeem_credits
from apps.loyalty.models import LoyaltySettings
from apps.notifications.services import notify_order, notify_order_staff
from apps.offers.models import Coupon, CouponRedemption, Offer, OfferRedemption
from apps.offers.services import get_valid_coupon
from apps.payments.cod_rules import cod_eligibility
from apps.payments.models import Payment, Refund
from apps.payments.refunds import create_refund
from integrations.payments import get_payment_provider
from integrations.payments.registry import online_payments_enabled

from .delivery_info import delivery_sentence, refresh_delivery_estimate
from .models import Order, OrderItem, OrderShipment, OrderStatus, OrderStatusHistory, PaymentMethod, PaymentStatus
from .pricing import line_from_variant, paid_by_line, price_lines
from .shipments import LEFT_THE_STORE, mirror_order_status, sync_order_status
from .state_machine import (
    CUSTOMER_CANCELLABLE,
    DELIVERY_STATUSES,
    RETURN_WORKFLOW_STATUSES,
    STOCK_RESERVED_STATUSES,
    can_transition,
)

_ORDER_NO_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity


class OrderError(ServiceError):
    default_code = "order_error"


class InvalidTransition(ConflictError):
    default_code = "invalid_transition"


def generate_order_number() -> str:
    suffix = "".join(secrets.choice(_ORDER_NO_ALPHABET) for _ in range(6))
    return f"OD{timezone.localdate():%y%m%d}{suffix}"


def _plan(address, requirements: dict[int, int]) -> Plan:
    plan = plan_fulfillment(requirements, resolve_location(address=address))
    if plan.deliverable:
        return plan
    if plan.reason_code == "insufficient_stock":
        raise InsufficientStock(plan.message)
    raise OrderError(plan.message, code="not_deliverable", details={"reason": plan.reason_code})


class TotalsChanged(ConflictError):
    default_code = "totals_changed"


def find_idempotent_order(user, key: str | None) -> Order | None:
    if not key:
        return None
    return Order.objects.filter(user=user, idempotency_key=key).first()


def _record_status(order: Order, from_status: str, to_status: str, actor=None, note: str = "") -> None:
    OrderStatusHistory.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        changed_by=actor if getattr(actor, "is_authenticated", False) else None,
        note=note[:255],
    )


@transaction.atomic
def place_order(
    *,
    user,
    address_id: int,
    payment_method: str,
    coupon_code: str = "",
    customer_note: str = "",
    expected_total: Decimal | None = None,
    idempotency_key: str | None = None,
    use_credits: bool = False,
) -> tuple[Order, Payment]:
    """Create an order from the cart in one transaction (any failure rolls everything back).

    - `idempotency_key`: a repeat with the same key returns the first order unchanged.
    - `expected_total`: the grand total the customer was shown. If prices, stock-driven
      totals or the coupon changed since, nothing is created and `totals_changed` (409)
      returns the new figures for the customer to review.
    - `use_credits` (Phase 17): pay part of the order with shop credit; the amount is decided
      here (at most the shop's share), never by the client.
    """
    if payment_method not in PaymentMethod.values:
        raise OrderError("Unsupported payment method.", code="invalid_payment_method")
    if payment_method == PaymentMethod.ONLINE and not online_payments_enabled():
        raise OrderError(
            "Online payment isn't available yet. Please choose cash on delivery.", code="online_payment_unavailable"
        )

    # Serialize checkouts of the same customer: concurrent "Place order" clicks queue here.
    Cart.objects.get_or_create(user=user)
    Cart.objects.select_for_update().get(user=user)
    if existing := find_idempotent_order(user, idempotency_key):
        # A concurrent request with this key committed first (it held the cart lock). Callers
        # that report "created vs replayed" (the API: 201 vs 200) read this flag.
        existing.idempotent_replay = True
        return existing, existing.payments.order_by("-created_at").first()

    address = Address.objects.filter(pk=address_id, user=user).first()
    if address is None:
        raise NotFoundError("Delivery address not found.")

    items = list(
        CartItem.objects.select_for_update()
        .filter(cart__user=user)
        .select_related("variant__product__brand")
        .prefetch_related("variant__price_tiers")
        .order_by("id")
    )
    if not items:
        raise OrderError("Your cart is empty.", code="cart_empty")
    for item in items:
        variant, product = item.variant, item.variant.product
        if not (variant.is_active and product.is_purchasable):
            raise OrderError(
                f"{product.name} is no longer available. Remove it to continue.", code="product_unavailable"
            )
        if item.quantity > product.max_order_quantity:
            raise OrderError(
                f"You can order at most {product.max_order_quantity} of {product.name}.", code="max_quantity_exceeded"
            )

    # Which store(s) ship it, when it can arrive and which zone fee applies (reads stock; the
    # reservations below re-check it under row locks).
    plan = _plan(address, {item.variant_id: item.quantity for item in items})

    # Bulk tiers, offers, coupon and delivery fee: the one pricing engine (orders.pricing).
    lines = [line_from_variant(item.variant, item.quantity) for item in items]
    coupon = get_valid_coupon(coupon_code, user, lock=True) if coupon_code.strip() else None
    # Offers, then the coupon, then credits (if chosen): one engine, one result.
    pricing = price_lines(lines, coupon=coupon, fee_rule=plan.fee_rule, user=user, use_credits=use_credits)
    totals, offers = pricing.totals, pricing.offers
    if expected_total is not None and q(expected_total) != totals.grand_total:
        raise TotalsChanged(
            "Prices or your order total changed since you last checked. Please review the new total.",
            details={"expected": str(q(expected_total)), "grand_total": str(totals.grand_total)},
        )
    if payment_method == PaymentMethod.COD:
        cod = cod_eligibility(grand_total=totals.grand_total, plan=plan)
        if not cod.available:
            raise OrderError(cod.message, code="cod_unavailable", details={"reason": cod.reason_code})
    _claim_offers(offers, user, totals)
    cashback = cashback_for(user, lines, paid_by_line(lines, totals, offers.line_discounts))
    credit_rules = LoyaltySettings.load()

    latest = plan.latest
    order = Order.objects.create(
        order_number=_unique_order_number(),
        user=user,
        store=plan.primary.store,
        delivery_type=plan.delivery_type,
        eta_minutes=latest.eta_minutes,
        estimated_ready_at=max(e.ready_at for e in plan.estimates),
        estimated_delivery_at=latest.delivery_at,
        delivery_window_start=latest.window_start,
        delivery_window_end=latest.window_end,
        address_snapshot=address.snapshot(),
        payment_method=payment_method,
        subtotal=totals.subtotal,
        mrp_total=totals.mrp_total,
        discount_total=totals.discount_total,
        offer_discount=totals.offer_discount,
        coupon_discount=totals.coupon_discount,
        applied_offers=[
            {
                "id": a.offer.id,
                "name": a.offer.name,
                "badge": a.offer.badge,
                "discount": str(a.discount),
                "skus": [i.variant.sku for i in items if i.variant_id in a.variant_ids],
                "benefit": a.offer.benefit,
                "campaign": a.offer.campaign,
            }
            for a in offers.all_applied
        ],
        delivery_fee=totals.delivery_fee,
        free_delivery_reason=totals.free_delivery_reason[:160],
        tax_total=totals.tax_total,
        grand_total=totals.grand_total,
        credit_discount=totals.credit_discount,
        loyalty_snapshot={
            "max_order_share": str(credit_rules.max_order_share),
            "expiry_days": credit_rules.expiry_days,
            "credits_available": str(pricing.credits.balance) if pricing.credits else "0.00",
            "cashback": {
                "amount": str(cashback.amount),
                "rule_id": cashback.rule_id,
                "rule_name": cashback.rule_name,
                "summary": cashback.summary,
            },
        },
        coupon=coupon,
        coupon_code=coupon.code if coupon else "",
        customer_note=customer_note[:500],
        idempotency_key=idempotency_key or None,
    )
    shipment_of = {}
    for sequence, planned in enumerate(plan.shipments, start=1):
        shipment = _create_shipment(order, sequence, planned)
        shipment_of.update(dict.fromkeys(planned.lines, shipment))
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                shipment=shipment_of[item.variant_id],
                variant=item.variant,
                product=item.variant.product,
                product_name=item.variant.product.name,
                variant_name=item.variant.name,
                sku=item.variant.sku,
                brand_name=item.variant.product.brand.name if item.variant.product.brand else "",
                unit=item.variant.product.unit,
                unit_mrp=line.unit_mrp,
                unit_price=line.unit_price,
                base_unit_price=item.variant.price,
                price_tier_min_quantity=line.tier_min_quantity,
                gst_rate=line.gst_rate,
                hsn_code=item.variant.product.hsn_code,
                quantity=line.quantity,
                line_total=line.line_total,
                offer_discount=offers.line_discounts.get(line.variant_id, ZERO),
            )
            for item, line in zip(items, lines, strict=True)
        ]
    )

    # Reserve each line at its shipment's store (locks rows and re-validates; raises → full rollback).
    for item in items:
        inventory = Inventory.objects.filter(
            store=shipment_of[item.variant_id].store, variant_id=item.variant_id, is_active=True
        ).first()
        if inventory is None:
            raise InsufficientStock("Stock changed while you were checking out. Please review your cart.")
        apply_movement(
            inventory,
            StockMovement.Type.RESERVATION,
            item.quantity,
            reason="Order placed",
            reference_type="order",
            reference_id=order.order_number,
            actor=user,
        )

    if coupon:
        CouponRedemption.objects.create(coupon=coupon, user=user, order=order, discount_amount=totals.coupon_discount)
        type(coupon).objects.filter(pk=coupon.pk).update(used_count=F("used_count") + 1)
    for applied in offers.all_applied:
        OfferRedemption.objects.create(
            offer_id=applied.offer.id, user=user, order=order, discount_amount=applied.discount
        )
        Offer.objects.filter(pk=applied.offer.id).update(used_count=F("used_count") + 1)
    # Credits: locked and used oldest-expiry first; a changed balance rolls everything back (409).
    redeem_credits(user, order, totals.credit_discount)
    record_cashback(order, cashback)  # pending until delivery + return window

    _record_status(order, "", OrderStatus.PENDING, user, "Order placed")
    payment = create_payment_for_order(order)
    if payment_method == PaymentMethod.COD:
        # Cash orders need no online payment step; confirm immediately.
        _apply_transition(order, OrderStatus.CONFIRMED, actor=None, note="Cash on delivery order confirmed")
        notify_order(
            order,
            "order.confirmed",
            amount=order.grand_total,
            payment_method="cash on delivery",
            delivery_sentence=delivery_sentence(order),
        )
        tell_staff_new_order(order)
    else:
        notify_order(order, "order.placed", amount=order.grand_total)

    CartItem.objects.filter(pk__in=[item.pk for item in items]).delete()
    return order, payment


def _claim_offers(offers, user, totals) -> None:
    """Lock offers with usage limits and check they still have uses left for this customer. An offer
    that ran out between pricing and now would change the total: nothing is written and the
    customer reviews the new total (409 `totals_changed`)."""
    limited = [a.offer.id for a in offers.all_applied]
    if not limited:
        return
    for offer in Offer.objects.select_for_update().filter(pk__in=limited).order_by("pk"):
        exhausted = offer.usage_limit is not None and offer.used_count >= offer.usage_limit
        used_by_customer = (
            OfferRedemption.objects.filter(offer=offer, user=user).count()
            if offer.per_customer_limit is not None
            else 0
        )
        if exhausted or (offer.per_customer_limit is not None and used_by_customer >= offer.per_customer_limit):
            raise TotalsChanged(
                f"The offer \u201c{offer.name}\u201d has just run out. Please review the new total.",
                details={"offer": offer.name, "grand_total": str(totals.grand_total)},
            )


def _create_shipment(order: Order, sequence: int, planned) -> OrderShipment:
    e = planned.estimate
    return OrderShipment.objects.create(
        order=order,
        sequence=sequence,
        store=planned.store,
        zone=planned.zone,
        delivery_type=e.delivery_type,
        distance_km=round(Decimal(str(e.distance_km)), 2) if e.distance_km is not None else None,
        prep_minutes=e.prep_minutes,
        wait_minutes=e.wait_minutes,
        travel_minutes=e.travel_minutes,
        eta_minutes=e.eta_minutes,
        estimated_ready_at=e.ready_at,
        estimated_delivery_at=e.delivery_at,
        window_start=e.window_start,
        window_end=e.window_end,
        eta_source=e.eta_source,
    )


def _unique_order_number() -> str:
    for _ in range(10):
        number = generate_order_number()
        if not Order.objects.filter(order_number=number).exists():
            return number
    raise OrderError("Could not allocate an order number. Please retry.", code="order_number_exhausted")


def create_payment_for_order(order: Order) -> Payment:
    """COD: a pending cash record. Online: a new intent at the configured gateway (mock in dev)."""
    if order.payment_method == PaymentMethod.COD:
        return Payment.objects.create(
            order=order,
            provider=Payment.Provider.COD,
            method=Payment.Method.COD,
            amount=order.grand_total,
            status=Payment.Status.PENDING,
        )
    provider = get_payment_provider()
    user = order.user
    intent = provider.create_payment(
        reference=order.order_number,
        amount=order.grand_total,
        # Prefills the gateway form for the customer only; nothing here is secret.
        customer={"name": user.full_name, "email": user.email, "contact": getattr(user, "phone", "") or ""},
    )
    return Payment.objects.create(
        order=order,
        provider=provider.name,
        amount=intent.amount,
        currency=intent.currency,
        status=Payment.Status.CREATED,
        provider_order_id=intent.provider_order_id,
        metadata={"client_payload": intent.client_payload, "test_mode": provider.is_test_mode},
    )


def _apply_transition(order: Order, to_status: str, *, actor, note: str = "", mirror: bool = True) -> Order:
    """Validate + apply side effects + history. Caller must hold a lock on `order`.

    `mirror=True` (staff, customers, payments): the order leads and its shipments follow, with
    their stock. `mirror=False`: a delivery partner already changed the shipment
    (apps.delivery.workflow) and the order only catches up.
    """
    from_status = order.status
    if not can_transition(from_status, to_status):
        raise InvalidTransition(
            f"Cannot change order from '{from_status}' to '{to_status}'.",
            details={"from": from_status, "to": to_status},
        )

    if mirror:
        if to_status == OrderStatus.CANCELLED:
            on_the_way = [s for s in order.shipments.all() if s.status in LEFT_THE_STORE]
            if on_the_way:
                raise InvalidTransition(
                    "Part of this order is already with the delivery partner or delivered, so it can't be cancelled.",
                    code="shipment_on_the_way",
                    details={"from": from_status, "to": to_status},
                )
        # Going *back* to packed takes the riders off; reaching packed from processing does not.
        unassigning = to_status == OrderStatus.PACKED and from_status != OrderStatus.PROCESSING
        if to_status == OrderStatus.CANCELLED or unassigning:
            from apps.delivery.assignment import release_assignments

            release_assignments(order, reason="Order cancelled" if to_status == OrderStatus.CANCELLED else "Unassigned")
        # Lines without a shipment exist only on orders placed before Phase 9 without a store.
        if to_status == OrderStatus.CANCELLED and from_status in STOCK_RESERVED_STATUSES:
            _move_unshipped_stock(order, StockMovement.Type.RELEASE, actor, "Order cancelled")
        elif to_status == OrderStatus.PICKED_UP:
            _move_unshipped_stock(order, StockMovement.Type.SALE, actor, "Picked up for delivery")
        if to_status != OrderStatus.PACKED or unassigning:
            mirror_order_status(order, to_status, actor=actor)

    order.status = to_status
    fields = ["status", "updated_at"]
    now = timezone.now()
    if to_status == OrderStatus.CONFIRMED and order.payment_method == PaymentMethod.ONLINE:
        # Paid later than placed: the delivery clock starts now, at the same store(s).
        fields += refresh_delivery_estimate(order, now=now)
    if to_status == OrderStatus.CANCELLED:
        order.cancelled_at = now
        order.cancellation_reason = note[:255]
        fields += ["cancelled_at", "cancellation_reason"]
        # Uncaptured payments are void.
        order.payments.filter(status__in=[Payment.Status.CREATED, Payment.Status.PENDING]).update(
            status=Payment.Status.CANCELLED, updated_at=now
        )
        # Captured money goes back: a pending refund is recorded and queued for the gateway
        # (payments.refunds). payment_status changes only once the gateway confirms it.
        for payment in order.payments.filter(status=Payment.Status.CAPTURED):
            if not payment.refunds.exists():
                create_refund(payment, payment.amount, reason=f"Order cancelled: {note}", requested_by=actor)
        _release_coupon(order)
        on_order_cancelled(order)  # pending cashback reversed, used credits given back (Phase 17)
    elif to_status == OrderStatus.DELIVERED and not order.delivered_at:
        order.delivered_at = now
        fields.append("delivered_at")
        if order.payment_method == PaymentMethod.COD:
            # Cash is collected at the door: the COD record becomes captured money (refundable on return).
            collected = order.payments.filter(provider=Payment.Provider.COD, status=Payment.Status.PENDING).update(
                status=Payment.Status.CAPTURED, captured_at=now, method=Payment.Method.COD, updated_at=now
            )
            if collected:
                order.payment_status = PaymentStatus.PAID
                fields.append("payment_status")
        on_order_delivered(order)  # cashback/referral clock: usable after the return window
    order.save(update_fields=fields)
    _record_status(order, from_status, to_status, actor, note)
    return order


def apply_locked_transition(order: Order, to_status: str, *, actor, note: str = "", mirror: bool = True) -> Order:
    """For other services that already hold `select_for_update` on the order (e.g. payments)."""
    return _apply_transition(order, to_status, actor=actor, note=note, mirror=mirror)


def _release_coupon(order: Order) -> None:
    """A cancelled order gives the coupon use back (global and per-customer counts), and the uses
    of automatic offers with usage limits (Phase 15)."""
    redemptions = CouponRedemption.objects.filter(order=order)
    for redemption in redemptions.select_related("coupon"):
        Coupon.objects.filter(pk=redemption.coupon_id, used_count__gt=0).update(used_count=F("used_count") - 1)
    redemptions.delete()
    offer_uses = OfferRedemption.objects.filter(order=order)
    for offer_id in offer_uses.values_list("offer_id", flat=True):
        Offer.objects.filter(pk=offer_id, used_count__gt=0).update(used_count=F("used_count") - 1)
    offer_uses.delete()


def _move_unshipped_stock(order: Order, movement_type: str, actor, reason: str) -> None:
    """Lines that belong to no shipment move at the order's store. Every other line moves with
    its shipment, at that shipment's store (orders.shipments)."""
    for item in order.items.filter(shipment__isnull=True):
        if item.variant_id is None or order.store_id is None:
            continue
        inventory = Inventory.objects.filter(store_id=order.store_id, variant_id=item.variant_id).first()
        if inventory is None:
            raise OrderError(f"Inventory record missing for {item.sku}.", code="inventory_missing")
        apply_movement(
            inventory,
            movement_type,
            item.quantity,
            reason=reason,
            reference_type="order",
            reference_id=order.order_number,
            actor=actor,
        )


@transaction.atomic
def transition_order(order: Order, to_status: str, *, actor, note: str = "") -> Order:
    """Staff/system status change (validated against the state machine)."""
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if to_status in RETURN_WORKFLOW_STATUSES or locked.status in RETURN_WORKFLOW_STATUSES:
        raise InvalidTransition(
            "Returns are handled through the return request (approve, reject or receive it).",
            details={"from": locked.status, "to": to_status},
        )
    if to_status in DELIVERY_STATUSES and can_transition(locked.status, to_status):
        from apps.delivery.assignment import has_rider_in_charge

        if has_rider_in_charge(locked):
            raise ConflictError(
                "A delivery partner is handling this order and updates it from the rider app. "
                "Reassign or unassign the partner to change it from here.",
                code="rider_in_charge",
                details={"from": locked.status, "to": to_status},
            )
    from_status = locked.status
    _apply_transition(locked, to_status, actor=actor, note=note)
    if to_status == OrderStatus.PACKED:
        # Riders may have been assigned while the order was being packed.
        sync_order_status(locked, actor=actor, note="Delivery partner already assigned")
    if to_status == OrderStatus.CANCELLED and actor is not None:
        _tell_cancelled(locked)  # system cancellations (unpaid orders) send their own message
    elif to_status == OrderStatus.PROCESSING or (
        to_status == OrderStatus.PACKED and from_status == OrderStatus.PROCESSING
    ):
        _tell_progress(locked, to_status)  # not when a packed order only goes back to waiting for a rider
    record_audit(action="order.transition", actor=actor, target=locked, changes={"to": to_status, "note": note})
    return locked


@transaction.atomic
def cancel_order_by_customer(order: Order, *, user, reason: str) -> Order:
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.user_id != user.id:
        raise NotFoundError("Order not found.")
    if locked.status not in CUSTOMER_CANCELLABLE:
        raise InvalidTransition(
            "This order can no longer be cancelled online. Please contact support.",
            details={"status": locked.status},
        )
    if not reason.strip():
        raise OrderError("Please tell us why you are cancelling.", code="reason_required")
    order = _apply_transition(locked, OrderStatus.CANCELLED, actor=user, note=reason)
    _tell_cancelled(order)
    return order


def _tell_cancelled(order: Order) -> None:
    refund = Refund.objects.filter(payment__order=order).first()
    notify_order(
        order,
        "order.cancelled",
        refund_sentence=f"A refund of ₹{refund.amount} has been requested and will be processed to your original "
        "payment method."
        if refund
        else "No payment was taken.",
    )


def tell_staff_new_order(order: Order) -> None:
    """A confirmed order reaches the people who will prepare it."""
    notify_order_staff(
        order,
        "staff.order_new",
        amount=order.grand_total,
        store_name=", ".join(sorted({s.store.name for s in order.shipments.select_related("store")})) or "the shop",
        delivery_type=order.get_delivery_type_display().lower() if order.delivery_type else "delivery",
    )


def _tell_progress(order: Order, to_status: str) -> None:
    """Customer (and rider) messages for status changes made by the store."""
    store = ", ".join(sorted({s.store.name for s in order.shipments.select_related("store")})) or "The store"
    if to_status == OrderStatus.PROCESSING:
        notify_order(order, "order.accepted", store_name=store)
    elif to_status == OrderStatus.PACKED:
        notify_order(order, "order.packed")
        from apps.delivery.assignment import tell_riders_ready

        tell_riders_ready(order)


# --- Buy again ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReorderLine:
    sku: str
    name: str
    requested: int
    added: int = 0
    reason: str = ""  # why fewer (or none) were added


@transaction.atomic
def reorder(order: Order, *, user) -> list[ReorderLine]:
    """Put a past order's items back in the cart ("Buy again").

    Items are priced like any cart line (today's price, offers applied at checkout), never at
    the old order price. Each line is capped by current stock and the product's order limit,
    counting what is already in the cart; unavailable items are reported, not fatal.
    """
    if order.user_id != user.id:
        raise NotFoundError("Order not found.")
    cart, _ = Cart.objects.get_or_create(user=user)
    cart = Cart.objects.select_for_update().get(pk=cart.pk)
    in_cart = {item.variant_id: item for item in CartItem.objects.filter(cart=cart)}

    results = []
    for item in order.items.select_related("variant__product").order_by("id"):
        name = f"{item.product_name} — {item.variant_name}" if item.variant_name else item.product_name
        variant = item.variant
        if variant is None or not (variant.is_active and variant.product.is_purchasable):
            results.append(ReorderLine(item.sku, name, item.quantity, reason="No longer sold."))
            continue
        existing = in_cart.get(variant.id)
        current = existing.quantity if existing else 0
        available = total_available(variant.id)
        target = min(current + item.quantity, variant.product.max_order_quantity, available)
        added = max(target - current, 0)
        if added == 0:
            reason = "Out of stock right now." if available == 0 else "Your cart already has the most you can order."
        elif added < item.quantity:
            reason = f"Only {added} added (stock or order limit)."
        else:
            reason = ""
        if added:
            if existing:
                existing.quantity = target
                existing.save(update_fields=["quantity", "updated_at"])
            else:
                in_cart[variant.id] = CartItem.objects.create(
                    cart=cart, variant=variant, quantity=target, price_at_add=variant.price
                )
        results.append(ReorderLine(variant.sku, name, item.quantity, added, reason))
    added_lines = sum(1 for line in results if line.added)
    if added_lines:
        notify_order(order, "order.reorder", key=f"reorder:{order.order_number}:{timezone.now().isoformat()}",
                     item_count=added_lines)  # fmt: skip
    return results
