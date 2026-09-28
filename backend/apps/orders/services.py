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
from apps.notifications.services import notify
from apps.offers.models import Coupon, CouponRedemption
from apps.offers.services import get_valid_coupon
from apps.payments.models import Payment, Refund
from apps.payments.refunds import create_refund
from integrations.payments import get_payment_provider

from .delivery_info import delivery_sentence, refresh_delivery_estimate
from .models import Order, OrderItem, OrderShipment, OrderStatus, OrderStatusHistory, PaymentMethod, PaymentStatus
from .pricing import line_from_variant, price_lines
from .state_machine import (
    CUSTOMER_CANCELLABLE,
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
) -> tuple[Order, Payment]:
    """Create an order from the cart in one transaction (any failure rolls everything back).

    - `idempotency_key`: a repeat with the same key returns the first order unchanged.
    - `expected_total`: the grand total the customer was shown. If prices, stock-driven
      totals or the coupon changed since, nothing is created and `totals_changed` (409)
      returns the new figures for the customer to review.
    """
    if payment_method not in PaymentMethod.values:
        raise OrderError("Unsupported payment method.", code="invalid_payment_method")

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

    lines = [line_from_variant(item.variant, item.quantity) for item in items]
    coupon = get_valid_coupon(coupon_code, user, lock=True) if coupon_code.strip() else None
    pricing = price_lines(lines, coupon=coupon, fee_rule=plan.fee_rule)  # automatic offers, then the coupon
    totals, offers = pricing.totals, pricing.offers
    if expected_total is not None and q(expected_total) != totals.grand_total:
        raise TotalsChanged(
            "Prices or your order total changed since you last checked. Please review the new total.",
            details={"expected": str(q(expected_total)), "grand_total": str(totals.grand_total)},
        )

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
            }
            for a in offers.applied
        ],
        delivery_fee=totals.delivery_fee,
        tax_total=totals.tax_total,
        grand_total=totals.grand_total,
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

    _record_status(order, "", OrderStatus.PENDING, user, "Order placed")
    payment = create_payment_for_order(order)
    if payment_method == PaymentMethod.COD:
        # Cash orders need no online payment step; confirm immediately.
        _apply_transition(order, OrderStatus.CONFIRMED, actor=None, note="Cash on delivery order confirmed")
        notify(
            user,
            event="order.confirmed",
            title=f"Order {order.order_number} confirmed",
            body=f"Thank you! Your order of ₹{order.grand_total} (cash on delivery) is confirmed. "
            f"{delivery_sentence(order)}",
            data={"order_number": order.order_number},
        )
    else:
        notify(
            user,
            event="order.placed",
            title=f"Order {order.order_number} placed — payment pending",
            body=f"Complete the payment of ₹{order.grand_total} to confirm your order.",
            data={"order_number": order.order_number},
            channels=("in_app",),
        )

    CartItem.objects.filter(pk__in=[item.pk for item in items]).delete()
    return order, payment


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


def _apply_transition(order: Order, to_status: str, *, actor, note: str = "") -> Order:
    """Validate + apply side effects + history. Caller must hold a lock on `order`."""
    from_status = order.status
    if not can_transition(from_status, to_status):
        raise InvalidTransition(
            f"Cannot change order from '{from_status}' to '{to_status}'.",
            details={"from": from_status, "to": to_status},
        )

    if to_status == OrderStatus.CANCELLED or (from_status == OrderStatus.ASSIGNED and to_status == OrderStatus.PACKED):
        from apps.delivery.assignment import release_assignments

        release_assignments(order, reason="Order cancelled" if to_status == OrderStatus.CANCELLED else "Unassigned")
    if to_status == OrderStatus.CANCELLED and from_status in STOCK_RESERVED_STATUSES:
        _move_order_stock(order, StockMovement.Type.RELEASE, actor, "Order cancelled")
    elif to_status == OrderStatus.PICKED_UP:
        _move_order_stock(order, StockMovement.Type.SALE, actor, "Picked up for delivery")

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
    order.save(update_fields=fields)
    _record_status(order, from_status, to_status, actor, note)
    return order


def apply_locked_transition(order: Order, to_status: str, *, actor, note: str = "") -> Order:
    """For other services that already hold `select_for_update` on the order (e.g. payments)."""
    return _apply_transition(order, to_status, actor=actor, note=note)


def _release_coupon(order: Order) -> None:
    """A cancelled order gives the coupon use back (global and per-customer counts)."""
    redemptions = CouponRedemption.objects.filter(order=order)
    for redemption in redemptions.select_related("coupon"):
        Coupon.objects.filter(pk=redemption.coupon_id, used_count__gt=0).update(used_count=F("used_count") - 1)
    redemptions.delete()


def _move_order_stock(order: Order, movement_type: str, actor, reason: str) -> None:
    """Each line moves at the store it was reserved at (its shipment's; legacy orders: order.store)."""
    for item in order.items.select_related("shipment"):
        if item.variant_id is None:
            continue
        store_id = item.shipment.store_id if item.shipment_id else order.store_id
        inventory = Inventory.objects.filter(store_id=store_id, variant_id=item.variant_id).first()
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
    _apply_transition(locked, to_status, actor=actor, note=note)
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
    refund = Refund.objects.filter(payment__order=order).first()
    notify(
        user,
        event="order.cancelled",
        title=f"Order {order.order_number} cancelled",
        body=(
            f"Your order has been cancelled. A refund of ₹{refund.amount} has been requested and will be "
            "processed to your original payment method."
            if refund
            else "Your order has been cancelled. No payment was taken."
        ),
        data={"order_number": order.order_number},
    )
    return order


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
    return results
