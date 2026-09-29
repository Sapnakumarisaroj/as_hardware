"""Cash on delivery, from the door to the store's till (Phase 10).

A rider collects exactly `cod_amount_due` when completing a delivery (workflow.complete_delivery).
Cash stays "in hand" until store staff confirm they received it (workflow.hand_over_cash);
UPI payments go straight to the store, so there is nothing to hand over.
The order's payment record becomes `captured` when the whole order is delivered
(orders.services), exactly as before Phase 10.
"""

from decimal import Decimal

from django.db.models import Count, Sum

from apps.core.money import q

from .models import DeliveryAssignment

ZERO = Decimal("0.00")


def cash_not_handed_over(queryset=None):
    """Deliveries whose cash the rider still holds."""
    queryset = DeliveryAssignment.objects.all() if queryset is None else queryset
    return queryset.filter(
        cod_method=DeliveryAssignment.CodMethod.CASH, cod_collected_at__isnull=False, cod_handed_over_at__isnull=True
    )


def cash_in_hand(partner) -> Decimal:
    total = cash_not_handed_over(partner.assignments.all()).aggregate(total=Sum("cod_collected_amount"))["total"]
    return q(total or ZERO)  # SQLite returns sums without the two decimals


def cash_by_partner(partner_ids) -> dict[int, Decimal]:
    rows = (
        cash_not_handed_over()
        .filter(partner_id__in=list(partner_ids))
        .values("partner_id")
        .annotate(total=Sum("cod_collected_amount"), deliveries=Count("id"))
    )
    return {row["partner_id"]: q(row["total"] or ZERO) for row in rows}
