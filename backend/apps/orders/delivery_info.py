"""What the customer is told about an order's delivery (Phase 9).

The promise is made when the order is placed (and refreshed when an online order is paid later):
fast orders show the minutes left until the estimated time, standard orders show their window.
Orders placed before Phase 9 have no estimate and keep the older wording.
"""

import math
from datetime import datetime

from django.utils import timezone

from apps.delivery.eta import delivery_label

from .checkout import ETA_PENDING_MESSAGE
from .models import DeliveryType, Order, OrderStatus, PaymentMethod

IN_TRANSIT = (OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY)
FINISHED = (
    OrderStatus.DELIVERED,
    OrderStatus.DELIVERY_FAILED,  # the promise no longer holds; a new attempt is arranged
    OrderStatus.CANCELLED,
    OrderStatus.RETURN_REQUESTED,
    OrderStatus.RETURNED,
)


def minutes_left(order: Order, now: datetime | None = None) -> int | None:
    if not order.estimated_delivery_at:
        return None
    seconds = (order.estimated_delivery_at - (now or timezone.now())).total_seconds()
    return max(0, math.ceil(seconds / 60))


def describe_delivery(order: Order, now: datetime | None = None) -> dict:
    """Machine-readable delivery info for the API (labels are ready to display)."""
    now = now or timezone.now()
    has_estimate = bool(order.delivery_type and order.estimated_delivery_at)
    left = minutes_left(order, now)
    if not has_estimate:
        label = ""
    elif order.delivery_type == DeliveryType.FAST:
        label = f"Delivery in {left} minutes" if left else "Arriving any minute"
    else:
        label = delivery_label(order.delivery_type, None, order.delivery_window_start, order.delivery_window_end, now)
    return {
        "type": order.delivery_type or None,
        "type_label": DeliveryType(order.delivery_type).label if order.delivery_type else None,
        "fast": order.delivery_type == DeliveryType.FAST,
        "eta_minutes": order.eta_minutes,
        "minutes_left": left if has_estimate and order.status not in FINISHED else None,
        "estimated_ready_at": order.estimated_ready_at,
        "estimated_delivery_at": order.estimated_delivery_at,
        "window_start": order.delivery_window_start,
        "window_end": order.delivery_window_end,
        "label": label,
    }


def delivery_message(order: Order, now: datetime | None = None) -> str:
    """One honest line for lists and notifications, following the order status."""
    if order.status == OrderStatus.DELIVERED:
        return "Delivered"
    if order.status == OrderStatus.DELIVERY_FAILED:
        return "We couldn't deliver your order. The store will contact you to arrange another attempt."
    if order.status in (OrderStatus.CANCELLED, OrderStatus.RETURNED, OrderStatus.RETURN_REQUESTED):
        return ""
    if order.status == OrderStatus.PENDING and order.payment_method == PaymentMethod.ONLINE:
        return "Complete the payment to confirm your order."
    info = describe_delivery(order, now)
    if not info["label"]:
        return "Out for delivery — arriving soon." if order.status in IN_TRANSIT else ETA_PENDING_MESSAGE
    if info["fast"]:
        at = timezone.localtime(order.estimated_delivery_at).strftime("%I:%M %p").lstrip("0")
        prefix = "Out for delivery · " if order.status in IN_TRANSIT else "⚡ "
        return f"{prefix}{info['label']} (by about {at})" if info["minutes_left"] else f"{prefix}{info['label']}"
    return f"🚚 Standard delivery · {info['label']}"


def delivery_sentence(order: Order) -> str:
    info = describe_delivery(order)
    if not info["label"]:
        return ETA_PENDING_MESSAGE
    return f"Estimated delivery: {info['label']}."


def refresh_delivery_estimate(order: Order, now: datetime | None = None) -> list[str]:
    """Re-estimate every shipment (same stores) from `now`; returns the changed Order fields.
    Used when an online order is paid some time after it was placed."""
    from apps.delivery.fulfillment import reestimate_shipment

    shipments = list(order.shipments.select_related("store", "zone"))
    if not shipments:
        return []
    estimates = []
    for shipment in shipments:
        e = reestimate_shipment(shipment, now=now)
        shipment.delivery_type, shipment.eta_minutes = e.delivery_type, e.eta_minutes
        shipment.prep_minutes, shipment.wait_minutes, shipment.travel_minutes = (
            e.prep_minutes,
            e.wait_minutes,
            e.travel_minutes,
        )
        shipment.estimated_ready_at, shipment.estimated_delivery_at = e.ready_at, e.delivery_at
        shipment.window_start, shipment.window_end = e.window_start, e.window_end
        shipment.save(
            update_fields=["delivery_type", "eta_minutes", "prep_minutes", "wait_minutes", "travel_minutes",
                           "estimated_ready_at", "estimated_delivery_at", "window_start", "window_end"]
        )  # fmt: skip
        estimates.append(e)
    latest = max(estimates, key=lambda e: e.delivery_at)
    order.delivery_type = "fast" if all(e.fast_available for e in estimates) else "standard"
    order.eta_minutes = latest.eta_minutes
    order.estimated_ready_at = max(e.ready_at for e in estimates)
    order.estimated_delivery_at = latest.delivery_at
    order.delivery_window_start, order.delivery_window_end = latest.window_start, latest.window_end
    return ["delivery_type", "eta_minutes", "estimated_ready_at", "estimated_delivery_at",
            "delivery_window_start", "delivery_window_end"]  # fmt: skip
