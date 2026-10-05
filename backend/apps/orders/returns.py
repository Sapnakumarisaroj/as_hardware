"""Returns of delivered orders (Phase 7).

    customer: request_return ──► REQUESTED ──(cancel_return)──► CANCELLED
    staff:                        REQUESTED ──(approve_return)──► APPROVED
                                  REQUESTED/APPROVED ──(reject_return)──► REJECTED
                                  APPROVED ──(receive_return)──► RECEIVED (restock + pending refund)

The order follows along: DELIVERED → RETURN_REQUESTED while a request is open, then back to
DELIVERED (rejected, cancelled or a partial return received) or RETURNED once every unit has
come back. Only one request per order is open at a time; the order row lock serializes them.

Money: a returned unit refunds what the customer actually paid for it — the line total minus
the line's offer discount and its pro-rata share of the coupon (spread the same way GST is).
The delivery fee is not refunded. Refunds are recorded as *pending*; processing them at the
gateway (or paying cash back for COD) is Phase 8.
"""

import secrets
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.money import ZERO, q
from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import apply_movement
from apps.notifications.services import notify
from apps.payments.models import Payment
from apps.payments.refunds import create_refund

from .models import Order, OrderItem, OrderStatus, ReturnItem, ReturnRequest
from .services import apply_locked_transition

RS = ReturnRequest.Status
_NUMBER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ReturnError(ServiceError):
    default_code = "return_error"


class ReturnStateError(ConflictError):
    default_code = "return_state_invalid"


# --- Read helpers (also used by serializers; they work on prefetched relations) -------------


def return_deadline(order: Order) -> datetime | None:
    if order.delivered_at is None:
        return None
    return order.delivered_at + timedelta(days=settings.RETURN_WINDOW_DAYS)


def _spread(amounts: dict[int, Decimal], total: Decimal) -> dict[int, Decimal]:
    """Split `total` over `amounts` pro rata; the rounding remainder goes to the last line, so the
    shares add up exactly to `total`."""
    base = sum(amounts.values(), ZERO)
    total = min(total, base)
    if not total or not base:
        return dict.fromkeys(amounts, ZERO)
    result, allocated = {}, ZERO
    for index, (item_id, amount) in enumerate(amounts.items()):
        share = total - allocated if index == len(amounts) - 1 else q(total * amount / base)
        allocated += share
        result[item_id] = share
    return result


def credit_shares(order: Order, items: Iterable[OrderItem] | None = None) -> dict[int, Decimal]:
    """The shop credit used on each line (order_item.id → amount), Phase 17. Spread like the coupon,
    over the line amounts after offers and coupon. Always computed over all of the order's lines."""
    items = list(order.items.all()) if items is None else list(items)
    nets = {item.id: max(item.line_total - item.offer_discount, ZERO) for item in items}
    coupons = _spread(nets, order.coupon_discount)
    after_coupon = {item_id: net - coupons[item_id] for item_id, net in nets.items()}
    return _spread(after_coupon, order.credit_discount)


def paid_amounts(order: Order, items: Iterable[OrderItem] | None = None) -> dict[int, Decimal]:
    """What the customer paid for each line (order_item.id → amount), after offers, coupon and
    credits. Coupon and credits are spread pro rata over the post-offer line amounts, and the rounding
    remainder goes to the last line, so the shares add up exactly to the order's figures. Credits
    are not money: a refund pays back what was paid, and the credits come back as credits."""
    items = list(items if items is not None else order.items.all())
    nets = {item.id: max(item.line_total - item.offer_discount, ZERO) for item in items}
    coupons = _spread(nets, order.coupon_discount)
    after_coupon = {item_id: net - coupons[item_id] for item_id, net in nets.items()}
    credits = _spread(after_coupon, order.credit_discount)
    return {item_id: q(amount - credits[item_id]) for item_id, amount in after_coupon.items()}


def counted_quantities(returns: Iterable[ReturnRequest], statuses=ReturnRequest.COUNTED_STATUSES) -> dict[int, int]:
    """order_item.id → units in returns with one of `statuses` (default: no longer returnable)."""
    counts: dict[int, int] = defaultdict(int)
    for ret in returns:
        if ret.status in statuses:
            for line in ret.items.all():
                counts[line.order_item_id] += line.quantity
    return counts


def returnable_quantities(order: Order) -> dict[int, int]:
    """order_item.id → units the customer could still ask to return (ignores the time window)."""
    counted = counted_quantities(order.returns.all())
    result = {}
    for item in order.items.all():
        allowed = item.product.is_returnable if item.product_id else True
        result[item.id] = max(item.quantity - counted.get(item.id, 0), 0) if allowed else 0
    return result


def can_request_return(order: Order, now: datetime | None = None) -> bool:
    deadline = return_deadline(order)
    return (
        order.status == OrderStatus.DELIVERED
        and deadline is not None
        and (now or timezone.now()) <= deadline
        and any(returnable_quantities(order).values())
    )


# --- Workflows ------------------------------------------------------------------------------


def _unique_return_number() -> str:
    for _ in range(10):
        number = f"RT{timezone.localdate():%y%m%d}" + "".join(secrets.choice(_NUMBER_ALPHABET) for _ in range(6))
        if not ReturnRequest.objects.filter(return_number=number).exists():
            return number
    raise ReturnError("Could not allocate a return number. Please retry.", code="return_number_exhausted")


def _refund_payment(order: Order) -> Payment | None:
    """The payment a return refund is recorded against: the captured online payment, else the
    cash-on-delivery record."""
    payments = order.payments.all()
    return (
        payments.filter(status=Payment.Status.CAPTURED).order_by("-captured_at").first()
        or payments.filter(provider=Payment.Provider.COD).order_by("-created_at").first()
    )


@transaction.atomic
def request_return(order: Order, *, user, items: list[dict], reason: str, details: str = "") -> ReturnRequest:
    """Customer asks to return `items` ([{"order_item_id", "quantity"}]) of a delivered order."""
    order = Order.objects.select_for_update().filter(pk=order.pk, user=user).first()
    if order is None:
        raise NotFoundError("Order not found.")
    if order.status == OrderStatus.RETURN_REQUESTED:
        raise ReturnStateError(
            "A return is already open for this order. Wait for it to finish or cancel it first.", code="return_open"
        )
    if order.status != OrderStatus.DELIVERED:
        raise ReturnStateError("Only delivered orders can be returned.", code="order_not_delivered")
    deadline = return_deadline(order)
    if deadline is None or timezone.now() > deadline:
        raise ReturnError(
            f"The return window for this order has closed ({settings.RETURN_WINDOW_DAYS} days after delivery).",
            code="return_window_closed",
        )
    if reason not in ReturnRequest.Reason.values:
        raise ReturnError("Please choose a reason for the return.", code="reason_required")
    if reason == ReturnRequest.Reason.OTHER and not details.strip():
        raise ReturnError("Please describe the problem.", code="details_required")
    if not items:
        raise ReturnError("Choose at least one item to return.", code="no_items")

    order_items = {item.id: item for item in order.items.select_related("product")}
    returnable = returnable_quantities(order)
    counted = counted_quantities(order.returns.prefetch_related("items"))
    paid = paid_amounts(order, order_items.values())
    wanted: dict[int, int] = {}
    for entry in items:
        item_id, quantity = int(entry["order_item_id"]), int(entry["quantity"])
        item = order_items.get(item_id)
        if item is None or item_id in wanted:
            raise ReturnError("One of the items is not part of this order.", code="invalid_item")
        if quantity < 1:
            raise ReturnError("Quantity must be at least 1.", code="invalid_quantity")
        if quantity > returnable[item_id]:
            message = (
                f"{item.product_name} can't be returned."
                if returnable[item_id] == 0
                else f"You can return at most {returnable[item_id]} of {item.product_name}."
            )
            raise ReturnError(message, code="quantity_not_returnable", details={"order_item_id": item_id})
        wanted[item_id] = quantity

    lines = []
    for item_id, quantity in wanted.items():
        item, prior = order_items[item_id], counted.get(item_id, 0)
        # Cumulative rounding: returning every unit, in any number of requests, refunds exactly the line.
        amount = q(paid[item_id] * (prior + quantity) / item.quantity) - q(paid[item_id] * prior / item.quantity)
        lines.append((item, quantity, amount))

    payment = _refund_payment(order)
    ret = ReturnRequest.objects.create(
        return_number=_unique_return_number(),
        order=order,
        user=user,
        reason=reason,
        details=details.strip()[:500],
        refund_amount=q(sum((amount for _, _, amount in lines), ZERO)),
        refund_method=(
            ReturnRequest.RefundMethod.ORIGINAL_PAYMENT
            if payment is not None and payment.provider != Payment.Provider.COD
            else ReturnRequest.RefundMethod.MANUAL  # COD cash is paid back by the store
        ),
    )
    ReturnItem.objects.bulk_create(
        [ReturnItem(return_request=ret, order_item=item, quantity=qty, refund_amount=amt) for item, qty, amt in lines]
    )
    apply_locked_transition(
        order, OrderStatus.RETURN_REQUESTED, actor=user, note=f"Return {ret.return_number} requested"
    )
    notify(
        user,
        event="return.requested",
        title=f"Return {ret.return_number} requested",
        body=f"We received your return request for order {order.order_number}. We'll review it shortly.",
        data={"order_number": order.order_number, "return_number": ret.return_number},
        channels=("in_app",),
    )
    return ret


def _lock(ret: ReturnRequest) -> tuple[ReturnRequest, Order]:
    locked = ReturnRequest.objects.select_for_update().get(pk=ret.pk)
    return locked, Order.objects.select_for_update().get(pk=locked.order_id)


def _require(ret: ReturnRequest, *allowed: str, action: str) -> None:
    if ret.status not in allowed:
        raise ReturnStateError(
            f"This return is {ret.get_status_display().lower()} and can't be {action}.",
            details={"status": ret.status},
        )


def _reopen_order(order: Order, ret: ReturnRequest, actor, note: str) -> None:
    if order.status == OrderStatus.RETURN_REQUESTED:
        apply_locked_transition(order, OrderStatus.DELIVERED, actor=actor, note=note)


@transaction.atomic
def cancel_return(ret: ReturnRequest, *, user) -> ReturnRequest:
    """The customer withdraws a request that nobody has acted on yet."""
    ret, order = _lock(ret)
    if ret.user_id != user.id:
        raise NotFoundError("Return not found.")
    _require(ret, RS.REQUESTED, action="cancelled")
    ret.status, ret.cancelled_at = RS.CANCELLED, timezone.now()
    ret.save(update_fields=["status", "cancelled_at", "updated_at"])
    _reopen_order(order, ret, user, f"Return {ret.return_number} cancelled by customer")
    return ret


def _close_pickups(ret: ReturnRequest, actor, *, received: bool) -> None:
    """A rider sent to collect this return (Phase 10) is no longer needed."""
    from apps.delivery.assignment import close_return_pickups  # delivery imports orders

    close_return_pickups(ret, actor=actor, received=received)


def _decide(ret: ReturnRequest, status: str, actor, note: str) -> None:
    ret.status, ret.decision_note = status, note.strip()[:255]
    ret.decided_by, ret.decided_at = actor, timezone.now()
    ret.save(update_fields=["status", "decision_note", "decided_by", "decided_at", "updated_at"])


@transaction.atomic
def approve_return(ret: ReturnRequest, *, actor, note: str = "") -> ReturnRequest:
    ret, order = _lock(ret)
    _require(ret, RS.REQUESTED, action="approved")
    _decide(ret, RS.APPROVED, actor, note)
    record_audit(action="return.approve", actor=actor, target=ret, changes={"note": note})
    notify(
        ret.user,
        event="return.approved",
        title=f"Return {ret.return_number} approved",
        body="Your return was approved. Please hand the items over at pickup or at the store; "
        f"a refund of ₹{ret.refund_amount} starts once we receive them.",
        data={"order_number": order.order_number, "return_number": ret.return_number},
    )
    return ret


@transaction.atomic
def reject_return(ret: ReturnRequest, *, actor, note: str) -> ReturnRequest:
    if not note.strip():
        raise ReturnError("Tell the customer why the return is rejected.", code="note_required")
    ret, order = _lock(ret)
    _require(ret, RS.REQUESTED, RS.APPROVED, action="rejected")
    _decide(ret, RS.REJECTED, actor, note)
    _close_pickups(ret, actor, received=False)
    _reopen_order(order, ret, actor, f"Return {ret.return_number} rejected")
    record_audit(action="return.reject", actor=actor, target=ret, changes={"note": note})
    notify(
        ret.user,
        event="return.rejected",
        title=f"Return {ret.return_number} rejected",
        body=f"We couldn't accept your return: {ret.decision_note}",
        data={"order_number": order.order_number, "return_number": ret.return_number},
    )
    return ret


@transaction.atomic
def receive_return(ret: ReturnRequest, *, actor, note: str = "", restock: bool = True) -> ReturnRequest:
    """Staff confirm the items are back: optionally restock them and record the pending refund."""
    ret, order = _lock(ret)
    _require(ret, RS.APPROVED, action="marked received")
    lines = list(ret.items.select_related("order_item__shipment"))

    if restock:
        for line in lines:
            if line.order_item.variant_id is None:
                continue  # the variant was deleted from the catalog; nothing to restock
            # Back to the store it shipped from (split orders: that line's shipment store).
            shipment = line.order_item.shipment
            store_id = shipment.store_id if shipment else order.store_id
            inventory, _ = Inventory.objects.get_or_create(store_id=store_id, variant_id=line.order_item.variant_id)
            apply_movement(
                inventory,
                StockMovement.Type.RETURN,
                line.quantity,
                reason=f"Customer return {ret.return_number}",
                reference_type="return",
                reference_id=ret.return_number,
                actor=actor,
            )

    payment = _refund_payment(order)
    if ret.refund_amount > 0 and payment is not None:
        # Queued for the gateway right away (online); COD refunds wait for staff to pay them back.
        ret.refund = create_refund(
            payment,
            ret.refund_amount,
            reason=f"Return {ret.return_number} ({ret.get_reason_display()})",
            requested_by=actor,
        )
    _loyalty_after_return(ret, order, lines)
    ret.status, ret.received_at, ret.restocked = RS.RECEIVED, timezone.now(), restock
    if note.strip():
        ret.decision_note = note.strip()[:255]
    ret.save(update_fields=["status", "received_at", "restocked", "refund", "decision_note", "updated_at"])
    _close_pickups(ret, actor, received=True)

    received = counted_quantities(order.returns.prefetch_related("items"), statuses=(RS.RECEIVED,))
    everything_back = all(received.get(item.id, 0) >= item.quantity for item in order.items.all())
    apply_locked_transition(
        order,
        OrderStatus.RETURNED if everything_back else OrderStatus.DELIVERED,
        actor=actor,
        note=f"Return {ret.return_number} received" + ("" if everything_back else " (partial return)"),
    )
    record_audit(action="return.receive", actor=actor, target=ret, changes={"restock": restock, "note": note})
    method = (
        "to your original payment method"
        if ret.refund_method == ReturnRequest.RefundMethod.ORIGINAL_PAYMENT
        else "by the store (cash on delivery order)"
    )
    notify(
        ret.user,
        event="return.received",
        title=f"Return {ret.return_number} received",
        body=f"We received your returned items. A refund of ₹{ret.refund_amount} has been initiated {method}.",
        data={"order_number": order.order_number, "return_number": ret.return_number},
    )
    return ret


def _loyalty_after_return(ret: ReturnRequest, order: Order, lines) -> None:
    """Phase 17: credits used on the returned units come back (original expiry; expired ones don't),
    and the order's pending cashback shrinks by the share of the paid goods being refunded."""
    from apps.loyalty.ledger import on_return_received

    items = list(order.items.all())
    shares = credit_shares(order, items)
    paid = paid_amounts(order, items)
    by_id = {item.id: item for item in items}
    returned_credit = ZERO
    for line in lines:
        item = by_id.get(line.order_item_id)
        if item and item.quantity:
            returned_credit += shares.get(item.id, ZERO) * line.quantity / item.quantity
    on_return_received(
        ret,
        order,
        returned_credit=q(returned_credit),
        returned_paid=ret.refund_amount,
        paid_total=sum(paid.values(), ZERO),
        already_returned=sum(
            (r.refund_amount for r in order.returns.filter(status=RS.RECEIVED).exclude(pk=ret.pk)), ZERO
        ),
    )
