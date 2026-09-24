"""Order workflows: placement from the cart, status transitions, cancellation.

Everything runs inside a transaction: if any step fails (stock, coupon, payment intent),
nothing is written.
"""

import secrets
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import Address
from apps.carts.models import Cart, CartItem
from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.money import ZERO, q
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import InsufficientStock, apply_movement
from apps.notifications.services import notify
from apps.offers.models import Coupon, CouponRedemption
from apps.offers.services import get_valid_coupon
from apps.payments.models import Payment, Refund
from apps.stores.models import Store
from integrations.payments import get_payment_provider

from .checkout import ETA_PENDING_MESSAGE, find_fulfilment_store
from .models import Order, OrderItem, OrderStatus, OrderStatusHistory, PaymentMethod
from .pricing import line_from_variant, price_lines
from .state_machine import CUSTOMER_CANCELLABLE, STOCK_RESERVED_STATUSES, can_transition

_ORDER_NO_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity


class OrderError(ServiceError):
    default_code = "order_error"


class InvalidTransition(ConflictError):
    default_code = "invalid_transition"


def generate_order_number() -> str:
    suffix = "".join(secrets.choice(_ORDER_NO_ALPHABET) for _ in range(6))
    return f"OD{timezone.localdate():%y%m%d}{suffix}"


def _choose_store(requirements: dict[int, int]) -> Store:
    store = find_fulfilment_store(requirements)
    if store is None:
        raise InsufficientStock(
            "Some items are not available together at any store right now. Please reduce quantities or remove items."
        )
    return store


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

    lines = [line_from_variant(item.variant, item.quantity) for item in items]
    coupon = get_valid_coupon(coupon_code, user, lock=True) if coupon_code.strip() else None
    pricing = price_lines(lines, coupon=coupon)  # automatic offers, then the coupon
    totals, offers = pricing.totals, pricing.offers
    if expected_total is not None and q(expected_total) != totals.grand_total:
        raise TotalsChanged(
            "Prices or your order total changed since you last checked. Please review the new total.",
            details={"expected": str(q(expected_total)), "grand_total": str(totals.grand_total)},
        )

    store = _choose_store({item.variant_id: item.quantity for item in items})

    order = Order.objects.create(
        order_number=_unique_order_number(),
        user=user,
        store=store,
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
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
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

    # Reserve stock at the chosen store (locks rows and re-validates; raises → full rollback).
    inventories = {
        inv.variant_id: inv
        for inv in Inventory.objects.filter(store=store, variant_id__in=[i.variant_id for i in items])
    }
    for item in items:
        apply_movement(
            inventories[item.variant_id],
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
            f"{ETA_PENDING_MESSAGE}",
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
    intent = provider.create_payment(reference=order.order_number, amount=order.grand_total)
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

    if to_status == OrderStatus.CANCELLED and from_status in STOCK_RESERVED_STATUSES:
        _move_order_stock(order, StockMovement.Type.RELEASE, actor, "Order cancelled")
    elif to_status == OrderStatus.PICKED_UP:
        _move_order_stock(order, StockMovement.Type.SALE, actor, "Picked up for delivery")

    order.status = to_status
    fields = ["status", "updated_at"]
    now = timezone.now()
    if to_status == OrderStatus.CANCELLED:
        order.cancelled_at = now
        order.cancellation_reason = note[:255]
        fields += ["cancelled_at", "cancellation_reason"]
        # Uncaptured payments are void.
        order.payments.filter(status__in=[Payment.Status.CREATED, Payment.Status.PENDING]).update(
            status=Payment.Status.CANCELLED, updated_at=now
        )
        # Captured money: record a pending refund. It is *not* marked processed here; the
        # gateway refund workflow (Phase 8) processes it and updates payment_status.
        for payment in order.payments.filter(status=Payment.Status.CAPTURED):
            if not payment.refunds.exists():
                Refund.objects.create(
                    payment=payment,
                    amount=payment.amount,
                    reason=f"Order cancelled: {note}"[:255],
                    requested_by=actor if getattr(actor, "is_authenticated", False) else None,
                )
        _release_coupon(order)
    elif to_status == OrderStatus.DELIVERED and not order.delivered_at:
        order.delivered_at = now
        fields.append("delivered_at")
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
    for item in order.items.all():
        if item.variant_id is None:
            continue
        inventory = Inventory.objects.filter(store=order.store, variant_id=item.variant_id).first()
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
