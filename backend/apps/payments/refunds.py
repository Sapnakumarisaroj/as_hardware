"""Refunds: record → submit to the gateway → track until processed (Phase 8).

    create_refund()          a pending Refund row + a queued "payments.process_refund" job
    process_refund()         sends it to the gateway (idempotent by `provider_reference`)
    sync_refund()            asks the gateway how a submitted refund is doing
    webhook refund.*         (payments.services.process_webhook) same effect as sync
    mark_refund_processed()  staff record a manual refund (COD cash / paid outside the gateway)
    retry_refund()           staff retry a gateway refund that failed

Gateway calls never run inside a database transaction: the row is claimed and committed first,
the HTTP call is made, then the result is written under a fresh lock. A crash in between is
harmless because the next attempt reuses the same reference and gets the same gateway refund.

Payment and order `payment_status` move to partially_refunded / refunded only when money has
actually been refunded (status processed), never when a refund is merely requested.
"""

import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, ServiceError
from apps.core.jobs import enqueue
from apps.core.money import ZERO, q
from apps.notifications.services import notify
from apps.orders.models import Order, PaymentStatus
from integrations.payments import GatewayRejected, RefundResult, get_payment_provider

from .models import Payment, Refund

PROCESS_JOB = "payments.process_refund"
MONEY_HELD = (Payment.Status.CAPTURED, Payment.Status.PARTIALLY_REFUNDED, Payment.Status.REFUNDED)


class RefundError(ServiceError):
    default_code = "refund_error"


class RefundStateError(ConflictError):
    default_code = "refund_state_invalid"


def refundable_amount(payment: Payment) -> Decimal:
    """Captured money not yet promised back (pending or processed refunds count; failed ones don't)."""
    promised = payment.refunds.exclude(status=Refund.Status.FAILED).aggregate(total=Sum("amount"))["total"] or ZERO
    return q(payment.amount - promised)


def create_refund(payment: Payment, amount: Decimal, *, reason: str, requested_by=None) -> Refund:
    """Record a refund of captured money and queue it for the gateway (after the transaction commits)."""
    amount = q(amount)
    if amount <= 0:
        raise RefundError("Refund amount must be positive.", code="invalid_refund_amount")
    available = refundable_amount(payment)
    if amount > available:
        raise RefundError(
            f"Only ₹{available} of this payment can still be refunded.",
            code="refund_exceeds_payment",
            details={"refundable": str(available)},
        )
    public_id = uuid.uuid4()
    refund = Refund.objects.create(
        public_id=public_id,
        payment=payment,
        amount=amount,
        reason=reason[:255],
        requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
        provider_reference=f"{public_id.hex}-1",
    )
    schedule(refund)
    return refund


def schedule(refund: Refund) -> None:
    if not refund.is_manual:
        enqueue(PROCESS_JOB, {"refund_id": refund.pk}, dedupe_key=f"refund:{refund.pk}")


def process_refund(refund_id: int) -> str:
    """Submit a pending refund to its gateway. Raises GatewayError (→ job retry) on temporary failures."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("payment").get(pk=refund_id)
        if refund.status != Refund.Status.PENDING or refund.is_manual:
            return "skipped"
        if refund.provider_refund_id:
            return sync_refund(refund_id)
        if not refund.payment.provider_payment_id:
            _finish(refund, RefundResult(False, status="failed", failure_reason="Payment has no gateway id."))
            return "failed"
        refund.attempts += 1
        refund.last_attempt_at = timezone.now()
        refund.save(update_fields=["attempts", "last_attempt_at", "updated_at"])
        payment = refund.payment
        amount, reference = refund.amount, refund.provider_reference

    provider = get_payment_provider(payment.provider)
    try:
        result = provider.refund(provider_payment_id=payment.provider_payment_id, amount=amount, reference=reference)
    except GatewayRejected as exc:
        result = RefundResult(False, status="failed", failure_reason=str(exc)[:255])
    return apply_refund_result(refund_id, result)


def sync_refund(refund_id: int) -> str:
    refund = Refund.objects.select_related("payment").get(pk=refund_id)
    if refund.status != Refund.Status.PENDING or not refund.provider_refund_id:
        return "skipped"
    Refund.objects.filter(pk=refund_id).update(last_attempt_at=timezone.now())
    provider = get_payment_provider(refund.payment.provider)
    result = provider.fetch_refund(
        provider_payment_id=refund.payment.provider_payment_id, provider_refund_id=refund.provider_refund_id
    )
    return apply_refund_result(refund_id, result)


def apply_refund_result(refund_id: int, result: RefundResult) -> str:
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("payment").get(pk=refund_id)
        if refund.status != Refund.Status.PENDING:
            return refund.status  # already final (e.g. a webhook got there first)
        _finish(refund, result)
        return refund.status


def _finish(refund: Refund, result: RefundResult) -> None:
    """Write a gateway result onto a locked refund; on success update payment/order totals."""
    fields = ["status", "failure_reason", "updated_at"]
    if result.provider_refund_id and not refund.provider_refund_id:
        refund.provider_refund_id = result.provider_refund_id
        fields.append("provider_refund_id")
    if result.status == "processed":
        refund.status, refund.failure_reason, refund.processed_at = Refund.Status.PROCESSED, "", timezone.now()
        fields.append("processed_at")
    elif result.status == "failed":
        refund.status, refund.failure_reason = Refund.Status.FAILED, (result.failure_reason or "Refund failed.")[:255]
        record_audit(action="refund.failed", target=refund, changes={"reason": refund.failure_reason})
    refund.save(update_fields=fields)
    if refund.status == Refund.Status.PROCESSED:
        _after_processed(refund)


def _after_processed(refund: Refund) -> None:
    order = update_refund_totals(refund.payment)
    how = "by the store" if refund.is_manual else "to your original payment method"
    notify(
        order.user,
        event="refund.processed",
        title=f"Refund of ₹{refund.amount} processed",
        body=f"Your refund of ₹{refund.amount} for order {order.order_number} has been paid {how}. "
        + ("" if refund.is_manual else "Banks can take 5–7 working days to show it."),
        data={"order_number": order.order_number, "refund": str(refund.public_id)},
    )


def update_refund_totals(payment: Payment) -> Order:
    """Derive payment/order refund status from processed refunds. Call inside a transaction."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)  # payment before order, as everywhere
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    refunded = payment.refunds.filter(status=Refund.Status.PROCESSED).aggregate(t=Sum("amount"))["t"] or ZERO
    if payment.status in MONEY_HELD:
        status = (
            Payment.Status.REFUNDED
            if refunded >= payment.amount
            else Payment.Status.PARTIALLY_REFUNDED
            if refunded > 0
            else Payment.Status.CAPTURED
        )
        if status != payment.status:
            payment.status = status
            payment.save(update_fields=["status", "updated_at"])

    held = order.payments.filter(status__in=MONEY_HELD)
    captured_total = held.aggregate(t=Sum("amount"))["t"] or ZERO
    refunded_total = (
        Refund.objects.filter(payment__order=order, status=Refund.Status.PROCESSED).aggregate(t=Sum("amount"))["t"]
        or ZERO
    )
    if captured_total > 0:
        new = (
            PaymentStatus.REFUNDED
            if refunded_total >= captured_total
            else PaymentStatus.PARTIALLY_REFUNDED
            if refunded_total > 0
            else PaymentStatus.PAID
        )
        if new != order.payment_status:
            order.payment_status = new
            order.save(update_fields=["payment_status", "updated_at"])
    return order


# --- Staff actions ---------------------------------------------------------------------------


@transaction.atomic
def mark_refund_processed(refund: Refund, *, actor, reference: str) -> Refund:
    """Record money paid back outside the gateway (COD cash/UPI, or after a gateway failure)."""
    if not reference.strip():
        raise RefundError("Enter the UPI/bank reference or cash receipt number.", code="reference_required")
    refund = Refund.objects.select_for_update().select_related("payment").get(pk=refund.pk)
    allowed = (Refund.Status.PENDING, Refund.Status.FAILED) if refund.is_manual else (Refund.Status.FAILED,)
    if refund.status not in allowed:
        raise RefundStateError(
            "Only cash-on-delivery refunds, or gateway refunds that failed, can be marked as paid by hand.",
            details={"status": refund.status},
        )
    refund.status, refund.processed_at = Refund.Status.PROCESSED, timezone.now()
    refund.manual_reference, refund.processed_by, refund.failure_reason = reference.strip()[:100], actor, ""
    refund.save(
        update_fields=["status", "processed_at", "manual_reference", "processed_by", "failure_reason", "updated_at"]
    )
    record_audit(action="refund.manual", actor=actor, target=refund, changes={"reference": refund.manual_reference})
    _after_processed(refund)
    return refund


@transaction.atomic
def retry_refund(refund: Refund, *, actor) -> Refund:
    refund = Refund.objects.select_for_update().select_related("payment").get(pk=refund.pk)
    if refund.status != Refund.Status.FAILED or refund.is_manual:
        raise RefundStateError("Only failed gateway refunds can be retried.", details={"status": refund.status})
    if refund.amount > refundable_amount(refund.payment):  # a failed refund no longer counts as promised
        raise RefundError("This payment has no refundable amount left.", code="refund_exceeds_payment")
    attempt = int(refund.provider_reference.rsplit("-", 1)[-1]) + 1 if "-" in refund.provider_reference else 2
    previous = refund.provider_refund_id
    refund.status, refund.provider_refund_id, refund.failure_reason = Refund.Status.PENDING, None, ""
    refund.provider_reference = f"{refund.public_id.hex}-{attempt}"
    refund.save(update_fields=["status", "provider_refund_id", "failure_reason", "provider_reference", "updated_at"])
    record_audit(action="refund.retry", actor=actor, target=refund, changes={"previous_provider_refund_id": previous})
    schedule(refund)
    return refund
