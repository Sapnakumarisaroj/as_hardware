"""Online payment workflows. The backend alone decides payment and order status.

Flow (development uses MockPaymentProvider; Razorpay plugs into the same interface in Phase 8):

    place_order (online) → Payment(status=created) + gateway intent → customer pays at the gateway
    → verify_payment(payload)  ── success   → Payment captured, Order.payment_status=paid, Order confirmed
                               ├─ failed    → Payment failed,  Order.payment_status=failed (retry allowed)
                               └─ cancelled → Payment cancelled, Order stays pending (retry or cancel order)

Each Payment row is locked while it is verified, so a double submit cannot capture twice.
"""

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ConflictError, NotFoundError
from apps.notifications.services import notify
from apps.orders.checkout import ETA_PENDING_MESSAGE
from apps.orders.models import Order, OrderStatus, PaymentMethod, PaymentStatus
from apps.orders.services import apply_locked_transition, create_payment_for_order
from integrations.payments import get_payment_provider

from .models import Payment, Refund


class PaymentStateError(ConflictError):
    default_code = "payment_state_invalid"


@transaction.atomic
def verify_payment(payment_public_id, *, user, payload: dict) -> Payment:
    payment = (
        Payment.objects.select_for_update()
        .select_related("order")
        .filter(public_id=payment_public_id, order__user=user)
        .first()
    )
    if payment is None:
        raise NotFoundError("Payment not found.")
    if payment.status == Payment.Status.CAPTURED:
        return payment  # already verified (repeat submit): idempotent
    if payment.status != Payment.Status.CREATED:
        raise PaymentStateError(
            "This payment attempt is closed. Start a new payment from your order.",
            details={"status": payment.status},
        )

    order = Order.objects.select_for_update().get(pk=payment.order_id)
    provider = get_payment_provider(payment.provider)
    result = provider.verify_payment(provider_order_id=payment.provider_order_id, payload=payload or {})
    now = timezone.now()

    if result.success:
        payment.status = Payment.Status.CAPTURED
        payment.provider_payment_id = result.provider_payment_id
        payment.method = result.method if result.method in Payment.Method.values else Payment.Method.UNKNOWN
        payment.captured_at = now
        payment.save(update_fields=["status", "provider_payment_id", "method", "captured_at", "updated_at"])
        order.payment_status = PaymentStatus.PAID
        order.save(update_fields=["payment_status", "updated_at"])
        if order.status == OrderStatus.PENDING:
            apply_locked_transition(order, OrderStatus.CONFIRMED, actor=None, note="Online payment received")
            notify(
                user,
                event="order.confirmed",
                title=f"Payment received — order {order.order_number} confirmed",
                body=f"We received ₹{payment.amount}. Your order is confirmed. {ETA_PENDING_MESSAGE}",
                data={"order_number": order.order_number},
            )
        else:
            # Paid after the order was cancelled: the money must go back (processed in Phase 8).
            Refund.objects.create(payment=payment, amount=payment.amount, reason="Payment received after cancellation")
        return payment

    payment.status = Payment.Status.CANCELLED if result.cancelled else Payment.Status.FAILED
    payment.failure_reason = result.failure_reason[:255]
    payment.save(update_fields=["status", "failure_reason", "updated_at"])
    if not result.cancelled:
        order.payment_status = PaymentStatus.FAILED
        order.save(update_fields=["payment_status", "updated_at"])
        notify(
            user,
            event="payment.failed",
            title=f"Payment failed for order {order.order_number}",
            body="Your payment did not go through and no money was taken. You can retry from your orders page.",
            data={"order_number": order.order_number},
            channels=("in_app",),
        )
    return payment


@transaction.atomic
def retry_payment(order: Order, *, user) -> Payment:
    """Start a new online payment attempt for a pending order whose last attempt failed/cancelled."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.user_id != user.id:
        raise NotFoundError("Order not found.")
    if order.payment_method != PaymentMethod.ONLINE or order.status != OrderStatus.PENDING:
        raise PaymentStateError("This order does not need a payment.")
    if order.payments.filter(status=Payment.Status.CAPTURED).exists():
        raise PaymentStateError("This order is already paid.")
    order.payments.filter(status=Payment.Status.CREATED).update(
        status=Payment.Status.CANCELLED, failure_reason="Superseded by a new attempt", updated_at=timezone.now()
    )
    payment = create_payment_for_order(order)
    order.payment_status = PaymentStatus.PENDING
    order.save(update_fields=["payment_status", "updated_at"])
    return payment
