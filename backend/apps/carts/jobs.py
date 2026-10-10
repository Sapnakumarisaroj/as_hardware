"""Cart recovery (run by `manage.py run_jobs`).

A customer whose cart has items and hasn't changed for CART_REMINDER_HOURS gets one `cart.reminder`
notification: in the app, by email, and on WhatsApp only when they opted in (the usual routing in
apps.notifications; they can also mute the "cart" category). One reminder per cart change: the cart's
`reminded_at` must be older than its newest item change. The item count and total come from
`summarize_cart` (today's prices, in-stock lines only), never from stored prices.

Off unless CART_REMINDERS_ENABLED is set. Nothing is sent during quiet hours (21:00 to 09:00 local
time); those carts are picked up on the first run in the morning.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from apps.core.jobs import periodic

from .models import Cart
from .services import summarize_cart

QUIET_FROM, QUIET_UNTIL = 21, 9  # local hours
BATCH = 200


def in_quiet_hours(now) -> bool:
    hour = timezone.localtime(now).hour
    return hour >= QUIET_FROM or hour < QUIET_UNTIL


def due_carts(now):
    """Carts with items, untouched for CART_REMINDER_HOURS and not reminded since their last change."""
    cutoff = now - timedelta(hours=settings.CART_REMINDER_HOURS)
    return (
        Cart.objects.filter(user__is_active=True, user__role="customer")
        .annotate(item_count=Count("items"), last_change=Max("items__updated_at"))
        .filter(item_count__gt=0, last_change__lte=cutoff)
        .filter(Q(reminded_at__isnull=True) | Q(reminded_at__lt=F("last_change")))
        .select_related("user")
        .order_by("last_change", "id")
    )


def send_cart_reminders(now=None) -> int:
    from apps.notifications.services import notify

    if not settings.CART_REMINDERS_ENABLED:
        return 0
    now = now or timezone.now()
    if in_quiet_hours(now):
        return 0
    sent = 0
    for cart in due_carts(now)[:BATCH]:
        with transaction.atomic():
            locked = Cart.objects.select_for_update().filter(pk=cart.pk).first()
            if locked is None:
                continue
            summary = summarize_cart(cart.user)
            Cart.objects.filter(pk=cart.pk).update(reminded_at=now)
            if not summary.priced_lines:
                continue  # nothing in stock to buy: no reminder for this change
            notify(
                cart.user,
                event="cart.reminder",
                context={"item_count": len(summary.priced_lines), "amount": summary.totals.grand_total},
                data={"cart_id": cart.pk},
                key=f"cart.reminder:{cart.pk}:{cart.last_change.isoformat()}",
            )
            sent += 1
    return sent


@periodic("carts.reminders")
def cart_reminders():
    return f"{send_cart_reminders()} cart reminder(s)"
