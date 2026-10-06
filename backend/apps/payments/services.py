"""Online payment workflows. The backend alone decides payment and order status.

    place_order (online) → Payment(created) + gateway order → customer pays in the gateway widget
    → verify_payment(payload)      browser report, checked with the gateway (signature + server fetch)
    → process_webhook(body)        gateway → us, HMAC-verified, each event handled once
    → reconcile_payment()          run_jobs asks the gateway about attempts left open (browser closed…)

All three end in the same two functions, so the outcome never depends on which arrives first:

    _record_capture   → Payment captured; order paid + confirmed. If the order was already paid by
                        another attempt, or cancelled/expired meanwhile, the money is refunded.
    _record_failure   → Payment failed/cancelled (only while still open; never un-captures).

Unpaid online orders expire after PAYMENT_EXPIRY_MINUTES (stock released) once the gateway
confirms nothing was captured. Payment rows are locked before order rows everywhere.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, NotFoundError, ServiceError
from apps.core.money import q
from apps.notifications.services import notify_order
from apps.orders.delivery_info import delivery_sentence
from apps.orders.models import Order, OrderStatus, PaymentMethod, PaymentStatus
from apps.orders.services import apply_locked_transition, create_payment_for_order, tell_staff_new_order
from integrations.payments import GatewayError, GatewayPayment, InvalidSignature, RefundResult, get_payment_provider
from integrations.payments.registry import ONLINE_PROVIDERS

from .models import Payment, Refund, WebhookEvent
from .refunds import MONEY_HELD, apply_refund_result, create_refund

logger = logging.getLogger(__name__)


class PaymentStateError(ConflictError):
    default_code = "payment_state_invalid"


class WebhookRejected(ServiceError):
    default_code = "invalid_webhook"


# --- Core state changes (caller holds locks on payment, then order) --------------------------


def _record_capture(
    payment: Payment, order: Order, *, provider_payment_id: str | None, method: str, amount: Decimal | None, source: str
) -> str:
    if payment.status in MONEY_HELD:
        return "already_captured"
    now = timezone.now()
    payment.status, payment.captured_at, payment.failure_reason = Payment.Status.CAPTURED, now, ""
    if provider_payment_id and not payment.provider_payment_id:
        payment.provider_payment_id = provider_payment_id
    payment.method = method if method in Payment.Method.values else Payment.Method.UNKNOWN
    payment.metadata = {**payment.metadata, "captured_via": source}
    fields = ["status", "captured_at", "failure_reason", "provider_payment_id", "method", "metadata", "updated_at"]

    if amount is not None and q(amount) != payment.amount:
        # Money was taken, but not the amount this order needs: never confirm on it; give it back.
        expected = payment.amount
        payment.amount, payment.failure_reason = q(amount), f"Amount mismatch: expected ₹{expected}"
        payment.save(update_fields=[*fields, "amount"])
        record_audit(
            action="payment.amount_mismatch", target=payment, changes={"expected": str(expected), "paid": str(amount)}
        )
        refund = create_refund(payment, payment.amount, reason="Paid amount did not match the order")
        notify_order(order, "refund.initiated", amount=refund.amount, data={"refund": str(refund.public_id)})
        return "refunded_mismatch"
    payment.save(update_fields=fields)

    paid_elsewhere = order.payments.filter(status__in=MONEY_HELD).exclude(pk=payment.pk).exists()
    if order.status == OrderStatus.CANCELLED or paid_elsewhere:
        reason = (
            "Payment received after the order was cancelled"
            if order.status == OrderStatus.CANCELLED
            else "Duplicate payment: the order was already paid"
        )
        refund = create_refund(payment, payment.amount, reason=reason)
        record_audit(action="payment.auto_refund", target=payment, changes={"reason": reason, "source": source})
        notify_order(order, "refund.initiated", amount=refund.amount, data={"refund": str(refund.public_id)})
        return "refunded_late"

    order.payment_status = PaymentStatus.PAID
    order.save(update_fields=["payment_status", "updated_at"])
    order.payments.filter(status=Payment.Status.CREATED).exclude(pk=payment.pk).update(
        status=Payment.Status.CANCELLED, failure_reason="Superseded: order already paid", updated_at=now
    )
    if order.status == OrderStatus.PENDING:
        apply_locked_transition(order, OrderStatus.CONFIRMED, actor=None, note="Online payment received")
        notify_order(order, "payment.succeeded", amount=payment.amount, delivery_sentence=delivery_sentence(order))
        tell_staff_new_order(order)
    return "captured"


def _record_failure(payment: Payment, order: Order, *, reason: str, cancelled: bool) -> str:
    if payment.status != Payment.Status.CREATED:
        return "ignored"  # already closed or captured: a late failure never undoes a capture
    payment.status = Payment.Status.CANCELLED if cancelled else Payment.Status.FAILED
    payment.failure_reason = reason[:255]
    payment.save(update_fields=["status", "failure_reason", "updated_at"])
    if not cancelled and order.status == OrderStatus.PENDING and order.payment_status != PaymentStatus.PAID:
        order.payment_status = PaymentStatus.FAILED
        order.save(update_fields=["payment_status", "updated_at"])
        notify_order(order, "payment.failed", data={"payment": payment.pk})
    return "cancelled" if cancelled else "failed"


def _lock_pair(payment_pk: int) -> tuple[Payment, Order]:
    payment = Payment.objects.select_for_update().get(pk=payment_pk)
    return payment, Order.objects.select_for_update().get(pk=payment.order_id)


def apply_gateway_payment(payment_pk: int, gateway: GatewayPayment, *, source: str) -> str:
    """Apply what the gateway says about one attempt (webhook or reconciliation)."""
    with transaction.atomic():
        payment, order = _lock_pair(payment_pk)
        if gateway.status == "captured":
            return _record_capture(
                payment,
                order,
                provider_payment_id=gateway.provider_payment_id,
                method=gateway.method,
                amount=gateway.amount,
                source=source,
            )
        if gateway.status == "failed":
            return _record_failure(payment, order, reason=gateway.failure_reason or "Payment failed.", cancelled=False)
        return "no_change"


# --- Browser report ---------------------------------------------------------------------------


def verify_payment(payment_public_id, *, user, payload: dict) -> Payment:
    """Check what the browser reported with the gateway, then apply it. Never trusts the browser alone."""
    payment = Payment.objects.filter(public_id=payment_public_id, order__user=user).first()
    if payment is None or payment.provider not in ONLINE_PROVIDERS:
        raise NotFoundError("Payment not found.")
    if payment.status in MONEY_HELD:
        return payment  # already verified (repeat submit): idempotent

    provider = get_payment_provider(payment.provider)
    try:
        result = provider.verify_payment(
            provider_order_id=payment.provider_order_id, payload=payload or {}, expected_amount=payment.amount
        )
    except GatewayError as exc:
        raise PaymentStateError(
            "We couldn't confirm the payment with the gateway right now. If money was taken, your order will be "
            "confirmed automatically within a few minutes.",
            code="payment_verification_unavailable",
        ) from exc

    with transaction.atomic():
        payment, order = _lock_pair(payment.pk)
        if result.success:
            _record_capture(
                payment,
                order,
                provider_payment_id=result.provider_payment_id,
                method=result.method,
                amount=result.amount,
                source="checkout",
            )
            return payment
        if payment.status in MONEY_HELD:
            return payment  # a webhook captured it meanwhile
        if payment.status != Payment.Status.CREATED:
            raise PaymentStateError(
                "This payment attempt is closed. Start a new payment from your order.",
                details={"status": payment.status},
            )
        if result.pending:
            payment.metadata = {**payment.metadata, "gateway_pending_since": timezone.now().isoformat()}
            payment.save(update_fields=["metadata", "updated_at"])
            return payment
        _record_failure(payment, order, reason=result.failure_reason or "Payment failed.", cancelled=result.cancelled)
        return payment


@transaction.atomic
def retry_payment(order: Order, *, user) -> Payment:
    """Start a new online payment attempt for a pending order whose last attempt failed/cancelled."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.user_id != user.id:
        raise NotFoundError("Order not found.")
    if order.payment_method != PaymentMethod.ONLINE or order.status != OrderStatus.PENDING:
        raise PaymentStateError("This order does not need a payment.")
    if order.payments.filter(status__in=MONEY_HELD).exists():
        raise PaymentStateError("This order is already paid.")
    order.payments.filter(status=Payment.Status.CREATED).update(
        status=Payment.Status.CANCELLED, failure_reason="Superseded by a new attempt", updated_at=timezone.now()
    )
    payment = create_payment_for_order(order)
    order.payment_status = PaymentStatus.PENDING
    order.save(update_fields=["payment_status", "updated_at"])
    return payment


# --- Webhooks ---------------------------------------------------------------------------------


def process_webhook(provider_name: str, *, body: bytes, headers) -> WebhookEvent:
    """Verify, de-duplicate and apply one webhook delivery.

    Idempotent: the (provider, event id) row is unique; a redelivery of a processed event only bumps
    `deliveries`. If applying fails, the row is marked failed and the error propagates (HTTP 500),
    so the gateway redelivers and the next delivery tries again.
    """
    if provider_name not in ONLINE_PROVIDERS or provider_name != settings.PAYMENT_PROVIDER:
        raise NotFoundError("Unknown webhook.")
    try:
        event = get_payment_provider(provider_name).parse_webhook(body=body, headers=headers)
    except InvalidSignature as exc:
        logger.warning("Rejected %s webhook: %s", provider_name, exc)
        raise WebhookRejected("Invalid webhook signature.") from exc

    try:
        with transaction.atomic():
            row, created = WebhookEvent.objects.get_or_create(
                provider=provider_name,
                event_id=event.event_id,
                defaults={"event_type": event.event_type, "payload": event.data},
            )
    except IntegrityError:  # a concurrent delivery of the same event created it first
        row, created = WebhookEvent.objects.get(provider=provider_name, event_id=event.event_id), False

    with transaction.atomic():
        row = WebhookEvent.objects.select_for_update().get(pk=row.pk)
        if not created:
            row.deliveries += 1
            row.save(update_fields=["deliveries"])
            if row.status in (WebhookEvent.Status.PROCESSED, WebhookEvent.Status.IGNORED):
                return row  # duplicate delivery: already handled

    try:
        note = _dispatch(provider_name, event)
    except Exception as exc:
        WebhookEvent.objects.filter(pk=row.pk).update(status=WebhookEvent.Status.FAILED, note=str(exc)[:255])
        raise
    status = WebhookEvent.Status.IGNORED if note.startswith("ignored") else WebhookEvent.Status.PROCESSED
    WebhookEvent.objects.filter(pk=row.pk).update(status=status, note=note[:255], processed_at=timezone.now())
    row.refresh_from_db()
    return row


def _dispatch(provider_name: str, event) -> str:
    kind = event.event_type
    if kind in ("payment.captured", "payment.failed", "payment.authorized", "order.paid") and event.payment:
        gateway = event.payment
        payment = Payment.objects.filter(provider=provider_name, provider_order_id=gateway.provider_order_id).first()
        if payment is None:
            return f"ignored: no payment for gateway order {gateway.provider_order_id}"
        if gateway.status == "authorized":
            gateway = get_payment_provider(provider_name).capture(
                provider_payment_id=gateway.provider_payment_id, amount=gateway.amount, currency=gateway.currency
            )
        return f"payment {payment.public_id}: " + apply_gateway_payment(payment.pk, gateway, source=f"webhook:{kind}")

    if kind.startswith("refund.") and event.refund:
        refund = Refund.objects.filter(provider_refund_id=event.refund.provider_refund_id).first()
        if refund is None:
            return f"ignored: unknown refund {event.refund.provider_refund_id}"
        if event.refund.status not in ("processed", "failed"):
            return "ignored: refund still pending"
        result = RefundResult(
            success=event.refund.status == "processed",
            provider_refund_id=event.refund.provider_refund_id,
            status=event.refund.status,
            failure_reason="Refund failed at the gateway." if event.refund.status == "failed" else "",
        )
        return f"refund {refund.public_id}: " + apply_refund_result(refund.pk, result)
    return f"ignored: {kind}"


# --- Recovery (run_jobs) ------------------------------------------------------------------------


def reconcile_payment(payment_pk: int) -> str:
    """Ask the gateway about one attempt and apply the truth (captures the browser never reported)."""
    payment = Payment.objects.get(pk=payment_pk)
    if payment.provider not in ONLINE_PROVIDERS or payment.status in MONEY_HELD or not payment.provider_order_id:
        return "skipped"
    provider = get_payment_provider(payment.provider)
    attempts = provider.fetch_order_payments(provider_order_id=payment.provider_order_id)
    Payment.objects.filter(pk=payment_pk).update(
        metadata={**payment.metadata, "reconciled_at": timezone.now().isoformat()}
    )
    captured = next((a for a in attempts if a.status == "captured"), None)
    authorized = next((a for a in attempts if a.status == "authorized"), None)
    if captured is None and authorized is not None:
        captured = provider.capture(
            provider_payment_id=authorized.provider_payment_id, amount=authorized.amount, currency=authorized.currency
        )
    if captured is not None and captured.status == "captured":
        return apply_gateway_payment(payment_pk, captured, source="reconciliation")
    return "nothing_captured"


def reconcile_stale_payments(now=None) -> int:
    """Online attempts still open (or closed by the browser) for a while: check the gateway.
    Covers payments whose confirmation never reached us (closed tab, lost webhook)."""
    now = now or timezone.now()
    older_than = now - timedelta(minutes=settings.PAYMENT_RECONCILE_AFTER_MINUTES)
    candidates = Payment.objects.filter(
        provider__in=ONLINE_PROVIDERS,
        status__in=[Payment.Status.CREATED, Payment.Status.CANCELLED, Payment.Status.FAILED],
        created_at__lte=older_than,
        created_at__gte=now - timedelta(days=2),
    ).filter(Q(order__status=OrderStatus.PENDING) | Q(status=Payment.Status.CREATED))
    count = 0
    for payment in candidates.order_by("created_at")[:200]:
        last = payment.metadata.get("reconciled_at")
        if last and datetime.fromisoformat(last) > now - timedelta(minutes=15):
            continue
        try:
            reconcile_payment(payment.pk)
            count += 1
        except GatewayError as exc:
            logger.warning("Reconciliation of payment %s postponed: %s", payment.pk, exc)
    return count


def expire_unpaid_orders(now=None) -> int:
    """Cancel online orders left unpaid past PAYMENT_EXPIRY_MINUTES, releasing their stock.
    The gateway is asked first; an order paid at the last minute is confirmed, not cancelled."""
    from apps.orders.services import transition_order

    now = now or timezone.now()
    cutoff = now - timedelta(minutes=settings.PAYMENT_EXPIRY_MINUTES)
    expired = 0
    stale = Order.objects.filter(
        status=OrderStatus.PENDING, payment_method=PaymentMethod.ONLINE, created_at__lte=cutoff
    ).exclude(payment_status=PaymentStatus.PAID)
    for order in stale.order_by("created_at")[:200]:
        try:
            for payment in order.payments.exclude(status__in=MONEY_HELD):
                reconcile_payment(payment.pk)
        except GatewayError as exc:
            logger.warning("Expiry of order %s postponed (gateway unreachable): %s", order.order_number, exc)
            continue
        order.refresh_from_db()
        if order.status != OrderStatus.PENDING or order.payment_status == PaymentStatus.PAID:
            continue  # paid after all
        try:
            transition_order(order, OrderStatus.CANCELLED, actor=None, note="Payment not completed in time")
        except ServiceError:
            continue  # changed concurrently
        expired += 1
        notify_order(order, "order.expired")
    return expired


__all__ = [
    "PaymentStateError",
    "apply_gateway_payment",
    "expire_unpaid_orders",
    "process_webhook",
    "reconcile_payment",
    "reconcile_stale_payments",
    "retry_payment",
    "verify_payment",
]
