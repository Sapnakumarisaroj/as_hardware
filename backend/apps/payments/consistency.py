"""Payment/order consistency checks (read-only). Run by `run_jobs` (logged) and `manage.py payments_check`.

Each issue is a dict {code, order, payment, message}. An empty list means the money records agree
with the order records.
"""

from django.db.models import Sum

from apps.core.money import ZERO
from apps.orders.models import Order, OrderStatus, PaymentMethod, PaymentStatus

from .models import Payment, Refund
from .refunds import MONEY_HELD

AFTER_PAYMENT = (
    OrderStatus.CONFIRMED,
    OrderStatus.PROCESSING,
    OrderStatus.PACKED,
    OrderStatus.ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERED,
    OrderStatus.RETURN_REQUESTED,
    OrderStatus.RETURNED,
)
DELIVERED_OR_LATER = (OrderStatus.DELIVERED, OrderStatus.RETURN_REQUESTED, OrderStatus.RETURNED)


def _issue(code, order=None, payment=None, message=""):
    return {
        "code": code,
        "order": order.order_number if order else None,
        "payment": str(payment.public_id) if payment else None,
        "message": message,
    }


def find_issues(limit: int = 500) -> list[dict]:
    issues: list[dict] = []

    # Paid orders must hold captured money; online orders past "pending" must have been paid.
    for order in Order.objects.filter(payment_status=PaymentStatus.PAID).exclude(payments__status__in=MONEY_HELD)[
        :limit
    ]:
        issues.append(
            _issue("paid_without_capture", order, message="Order is marked paid but has no captured payment.")
        )
    online_unpaid = Order.objects.filter(payment_method=PaymentMethod.ONLINE, status__in=AFTER_PAYMENT).exclude(
        payments__status__in=MONEY_HELD
    )
    for order in online_unpaid[:limit]:
        issues.append(_issue("fulfilled_without_payment", order, message=f"Online order is {order.status} but unpaid."))

    # Captured money on an order still waiting for payment: the confirmation was lost.
    for payment in Payment.objects.filter(status__in=MONEY_HELD, order__status=OrderStatus.PENDING).select_related(
        "order"
    )[:limit]:
        issues.append(
            _issue("captured_but_pending", payment.order, payment, "Payment captured but the order is still pending.")
        )

    # COD cash is collected at the door.
    cod_uncollected = Payment.objects.filter(
        provider=Payment.Provider.COD, status=Payment.Status.PENDING, order__status__in=DELIVERED_OR_LATER
    ).select_related("order")
    for payment in cod_uncollected[:limit]:
        issues.append(_issue("cod_not_collected", payment.order, payment, "COD order delivered but cash not recorded."))

    # Refunds can never exceed the captured amount, and statuses must follow processed refunds.
    for payment in Payment.objects.filter(status__in=MONEY_HELD).select_related("order")[:limit]:
        promised = payment.refunds.exclude(status=Refund.Status.FAILED).aggregate(t=Sum("amount"))["t"] or ZERO
        processed = payment.refunds.filter(status=Refund.Status.PROCESSED).aggregate(t=Sum("amount"))["t"] or ZERO
        if promised > payment.amount:
            issues.append(
                _issue("over_refunded", payment.order, payment, f"Refunds ₹{promised} exceed ₹{payment.amount}.")
            )
        expected = (
            Payment.Status.REFUNDED
            if processed >= payment.amount
            else Payment.Status.PARTIALLY_REFUNDED
            if processed > 0
            else Payment.Status.CAPTURED
        )
        if payment.status != expected:
            issues.append(
                _issue(
                    "refund_status_mismatch",
                    payment.order,
                    payment,
                    f"Payment is {payment.status}, expected {expected}.",
                )
            )
    return issues
