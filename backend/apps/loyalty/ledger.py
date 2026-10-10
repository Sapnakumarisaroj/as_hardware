"""The credit ledger (Phase 17): balance, redemption, restore, expiry, cashback and referral rewards.

Invariants (tested):
- balance = Σ amount of counted entries (`CreditEntry.COUNTED`); nothing else holds a balance;
- a lot's remaining amount = its amount − Σ allocations; never below zero;
- debits use the oldest-expiring lots first, under a row lock (two checkouts can't spend the same credit);
- credits pay at most `max_order_share` % of the goods amount after offers and coupon;
- cashback/referral credits stay pending until the return window after delivery has passed, and are
  reversed when the order is cancelled or (in proportion) returned;
- the welcome reward (first delivered order, once per customer) waits the same way and is reversed when the
  order is cancelled or fully returned;
- credits used on an order come back when the order is cancelled or the items are refunded on return, in
  proportion and with each lot's original expiry; credits whose expiry has passed are not given back.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.exceptions import ConflictError, ServiceError
from apps.core.money import ZERO, q

from .models import CashbackRule, CreditAllocation, CreditEntry, LoyaltySettings, Referral

K, S = CreditEntry.Kind, CreditEntry.Status


class CreditError(ServiceError):
    default_code = "credit_error"


class CreditsChanged(ConflictError):
    default_code = "totals_changed"


# --- Reading ---------------------------------------------------------------------------------------


def balance(user) -> Decimal:
    """Usable credit: the sum of counted ledger entries."""
    total = CreditEntry.objects.filter(user=user, status__in=CreditEntry.COUNTED).aggregate(t=Sum("amount"))["t"]
    return q(total or ZERO)


def pending_total(user) -> Decimal:
    """Earned but not usable yet (order not delivered, or inside its return window)."""
    total = CreditEntry.objects.filter(user=user, status__in=CreditEntry.WAITING).aggregate(t=Sum("amount"))["t"]
    return q(total or ZERO)


def _with_remaining(qs):
    used = (
        CreditAllocation.objects.filter(lot=OuterRef("pk"))
        .values("lot")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )
    money = DecimalField(max_digits=12, decimal_places=2)
    return qs.annotate(used=Coalesce(Subquery(used, output_field=money), Value(ZERO, output_field=money)))


def open_lots(user, *, now=None, lock: bool = False) -> list[CreditEntry]:
    """Available, unexpired credits with something left, oldest expiry first."""
    now = now or timezone.now()
    qs = CreditEntry.objects.filter(user=user, kind__in=CreditEntry.CREDIT_KINDS, status=S.AVAILABLE).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    if lock:
        # Lock the rows first (portable: no aggregate with FOR UPDATE), then read what is left.
        ids = list(qs.select_for_update().order_by("pk").values_list("pk", flat=True))
        qs = CreditEntry.objects.filter(pk__in=ids)
    lots = list(_with_remaining(qs).order_by("expires_at", "pk"))
    for lot in lots:
        lot.remaining = q(lot.amount - lot.used)
    return [lot for lot in lots if lot.remaining > 0]


def spendable(user, *, now=None) -> Decimal:
    """Credit that can be used right now (available and not past its expiry)."""
    return q(sum((lot.remaining for lot in open_lots(user, now=now)), ZERO))


def expiring_soon(user, days: int = 14) -> tuple[Decimal, object]:
    """Amount expiring within `days`, and the first expiry date."""
    limit = timezone.now() + timedelta(days=days)
    lots = [lot for lot in open_lots(user) if lot.expires_at and lot.expires_at <= limit]
    return q(sum((lot.remaining for lot in lots), ZERO)), (lots[0].expires_at if lots else None)


@dataclass(frozen=True)
class CreditQuote:
    enabled: bool
    balance: Decimal  # spendable now
    max_share: Decimal  # %
    cap: Decimal  # most credit this order may use
    usable: Decimal  # min(balance, cap)


def credit_quote(user, goods_amount: Decimal) -> CreditQuote:
    """What credits could pay on an order whose goods (after offers and coupon) cost `goods_amount`."""
    rules = LoyaltySettings.load()
    if user is None or not getattr(user, "is_authenticated", False) or not rules.credits_enabled:
        return CreditQuote(False, ZERO, rules.max_order_share, ZERO, ZERO)
    available = spendable(user)
    cap = q(max(goods_amount, ZERO) * rules.max_order_share / 100)
    return CreditQuote(True, available, rules.max_order_share, cap, q(min(available, cap)))


# --- Writing ----------------------------------------------------------------------------------------


def grant(
    user,
    kind: str,
    amount: Decimal,
    *,
    reference: str,
    description: str = "",
    actor=None,
    order=None,
    pending: bool = False,
    expiry_days: int | None = None,
    expires_at=None,
    source=None,
    return_request=None,
) -> CreditEntry:
    """Add a credit. Available credits expire `expiry_days` (default: the shop setting) from now unless
    `expires_at` is given (restored credits keep their original expiry)."""
    amount = q(Decimal(amount))
    if kind not in CreditEntry.CREDIT_KINDS or amount <= 0:
        raise CreditError("A credit needs a credit type and an amount above zero.", code="invalid_credit")
    if not reference.strip():
        raise CreditError("Every credit needs a reference (order, return or reason).", code="reference_required")
    if not pending and expires_at is None:
        days = expiry_days or LoyaltySettings.load().expiry_days
        expires_at = timezone.now() + timedelta(days=days)
    return CreditEntry.objects.create(
        user=user,
        kind=kind,
        status=S.PENDING if pending else S.AVAILABLE,
        amount=amount,
        expires_at=None if pending else expires_at,
        order=order,
        return_request=return_request,
        source=source,
        reference=reference.strip()[:80],
        description=description[:200],
        created_by=actor,
    )


def _debit(user, kind: str, amount: Decimal, lots, *, reference: str, description: str, order=None) -> CreditEntry:
    entry = CreditEntry.objects.create(
        user=user, kind=kind, status=S.POSTED, amount=-amount, order=order, reference=reference, description=description
    )
    left = amount
    rows = []
    for lot in lots:
        if left <= 0:
            break
        take = min(lot.remaining, left)
        rows.append(CreditAllocation(debit=entry, lot=lot, amount=take))
        lot.remaining -= take
        left -= take
    if left > 0:
        raise CreditsChanged(
            "Your credit balance changed while you were checking out. Please review the new total.",
            details={"missing": str(left)},
        )
    CreditAllocation.objects.bulk_create(rows)
    return entry


def redeem(user, order, amount: Decimal) -> CreditEntry | None:
    """Use `amount` of credit on `order` (call inside the order transaction). Oldest expiry first."""
    amount = q(amount)
    if amount <= 0:
        return None
    lots = open_lots(user, lock=True)
    return _debit(
        user,
        K.REDEMPTION,
        amount,
        lots,
        reference=order.order_number,
        description=f"Used on order {order.order_number}",
        order=order,
    )


def restore_for_order(order, amount: Decimal | None = None, *, reason: str, return_request=None) -> Decimal:
    """Give back credits used on `order`: all of what is left to give (cancellation) or `amount`
    (a refunded return). Spread over the lots in the order they were used, each restored credit keeping
    its lot's original expiry; parts of lots that have expired by now are not given back."""
    redemption = CreditEntry.objects.filter(order=order, kind=K.REDEMPTION).first()
    if redemption is None:
        return ZERO
    used = -redemption.amount
    # Returns pass the credit share of the returned items (so their sum never exceeds what was used);
    # a cancellation passes nothing and gets back everything not given back yet.
    already = CreditEntry.objects.filter(order=order, kind=K.RESTORE).aggregate(t=Sum("amount"))["t"] or ZERO
    target = q(min(used - already, amount if amount is not None else used))
    if target <= 0:
        return ZERO
    now = timezone.now()
    allocations = list(redemption.allocations.select_related("lot").order_by("lot__expires_at", "lot_id"))
    restored = ZERO
    remaining = target
    for index, allocation in enumerate(allocations):
        if remaining <= 0:
            break
        share = remaining if index == len(allocations) - 1 else min(q(target * allocation.amount / used), remaining)
        remaining -= share
        lot = allocation.lot
        if share <= 0 or (lot.expires_at is not None and lot.expires_at <= now):
            continue
        grant(
            order.user,
            K.RESTORE,
            share,
            reference=return_request.return_number if return_request else order.order_number,
            description=reason,
            order=order,
            expires_at=lot.expires_at,
            source=lot,
            return_request=return_request,
        )
        restored += share
    return q(restored)


def expire_due(now=None) -> int:
    """Expire what is left of lots past their expiry (periodic job). Returns lots expired."""
    now = now or timezone.now()
    count = 0
    due = CreditEntry.objects.filter(
        kind__in=CreditEntry.CREDIT_KINDS, status=S.AVAILABLE, expires_at__lte=now
    ).values_list("pk", flat=True)
    for pk in list(due[:500]):
        with transaction.atomic():
            lot = CreditEntry.objects.select_for_update().filter(pk=pk, status=S.AVAILABLE).first()
            if lot is None:
                continue
            used = lot.used_by.aggregate(t=Sum("amount"))["t"] or ZERO
            lot.remaining = q(lot.amount - used)
            if lot.remaining > 0:
                _debit(
                    lot.user,
                    K.EXPIRY,
                    lot.remaining,
                    [lot],
                    reference=f"expiry:{lot.pk}",
                    description=f"{lot.get_kind_display()} expired",
                )
            lot.status = S.EXPIRED
            lot.save(update_fields=["status", "updated_at"])
            count += 1
    return count


# --- Cashback and referral rewards ---------------------------------------------------------------------


def _live_rules(now=None):
    now = now or timezone.now()
    return (
        CashbackRule.objects.filter(is_active=True, starts_at__lte=now)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .prefetch_related("products", "categories")
        .order_by("priority", "pk")
    )


@dataclass(frozen=True)
class CashbackQuote:
    amount: Decimal
    rule_id: int | None = None
    rule_name: str = ""
    summary: str = ""


def cashback_for(user, lines, paid: dict[int, Decimal]) -> CashbackQuote:
    """Cashback for priced lines (`paid`: variant_id → what the customer pays for the line after offers,
    coupon and credits). The best single rule applies (lowest priority number among those that give
    something). Visitors earn nothing; first-order rules need no earlier (uncancelled) order."""
    if user is None or not getattr(user, "is_authenticated", False):
        return CashbackQuote(ZERO)
    rules = list(_live_rules())
    if not rules:
        return CashbackQuote(ZERO)
    from apps.catalog.tree import lineage, parent_map
    from apps.orders.models import Order, OrderStatus

    parents = parent_map()
    prior = None
    for rule in rules:
        product_ids = {p.pk for p in rule.products.all()}
        category_ids = {c.pk for c in rule.categories.all()}
        if rule.first_order_only:
            if prior is None:
                prior = Order.objects.filter(user=user).exclude(status=OrderStatus.CANCELLED).exists()
            if prior:
                continue
        eligible = ZERO
        for line in lines:
            if not product_ids and not category_ids:
                hit = True
            else:
                hit = line.product_id in product_ids or bool(
                    category_ids & lineage((line.category_id, line.subcategory_id), parents)
                )
            if hit:
                eligible += paid.get(line.variant_id, ZERO)
        eligible = q(eligible)
        if eligible <= 0 or eligible < rule.min_order_value:
            continue
        if rule.reward_type == CashbackRule.RewardType.FIXED:
            amount = q(min(rule.fixed_amount or ZERO, eligible))
        else:
            amount = q(eligible * (rule.percent or ZERO) / 100)
        if rule.max_amount is not None:
            amount = min(amount, rule.max_amount)
        if amount > 0:
            return CashbackQuote(amount, rule.pk, rule.name, rule.summary)
    return CashbackQuote(ZERO)


def record_cashback(order, quote: CashbackQuote) -> CreditEntry | None:
    if quote.amount <= 0:
        return None
    return grant(
        order.user,
        K.CASHBACK,
        quote.amount,
        reference=order.order_number,
        description=f"{quote.rule_name} ({quote.summary})",
        order=order,
        pending=True,
    )


def claim_referral(user, code: str) -> Referral:
    """A new customer (no orders yet) says who referred them. Rewards only follow if switched on."""
    from apps.orders.models import Order

    from .models import ReferralCode

    owner = ReferralCode.objects.filter(code=code.strip().upper()).select_related("user").first()
    if owner is None:
        raise CreditError("That referral code isn't valid.", code="invalid_referral_code")
    if owner.user_id == user.pk:
        raise CreditError("You can't use your own referral code.", code="own_referral_code")
    if Referral.objects.filter(referee=user).exists():
        raise CreditError("You have already used a referral code.", code="referral_already_used")
    if Order.objects.filter(user=user).exists():
        raise CreditError("Referral codes are for new customers before their first order.", code="not_a_new_customer")
    return Referral.objects.create(referrer=owner.user, referee=user)


# --- Order lifecycle hooks (called by orders.services / orders.returns inside their transactions) ----


#: Welcome rewards are promotional credits whose reference starts with this (no extra ledger kind needed).
WELCOME_PREFIX = "welcome:"


def is_welcome(entry: CreditEntry) -> bool:
    return entry.kind == K.PROMO and entry.reference.startswith(WELCOME_PREFIX)


def _grant_welcome(order, release_at) -> CreditEntry | None:
    """The shop's welcome reward for a customer's first delivered order: once per customer, ever (a reversed
    one counts), on the cashback terms — usable after the return window, reversed if the order comes back."""
    from django.contrib.auth import get_user_model

    from apps.orders.models import Order

    amount = LoyaltySettings.load().welcome_reward
    if amount <= 0:
        return None
    # Lock the customer so two deliveries at once can't both be "the first".
    get_user_model().objects.select_for_update().filter(pk=order.user_id).first()
    welcomed = CreditEntry.objects.filter(user_id=order.user_id, kind=K.PROMO, reference__startswith=WELCOME_PREFIX)
    if welcomed.exists():
        return None
    if Order.objects.filter(user_id=order.user_id, delivered_at__isnull=False).exclude(pk=order.pk).exists():
        return None  # not their first delivered order (e.g. delivered before the reward was switched on)
    entry = grant(
        order.user,
        K.PROMO,
        amount,
        reference=f"{WELCOME_PREFIX}{order.order_number}",
        description="Welcome reward: your first order was delivered",
        order=order,
        pending=True,
    )
    entry.status, entry.available_at = S.ELIGIBLE, release_at
    entry.save(update_fields=["status", "available_at"])
    return entry


def on_order_delivered(order) -> None:
    """Start the clock: pending credits of this order become usable when the return window ends.
    The customer's first delivered order also earns the welcome reward and triggers referral rewards
    (each only if switched on)."""
    release_at = order.delivered_at + timedelta(days=settings.RETURN_WINDOW_DAYS)
    CreditEntry.objects.filter(order=order, status=S.PENDING).update(
        status=S.ELIGIBLE, available_at=release_at, updated_at=timezone.now()
    )
    _grant_welcome(order, release_at)
    referral = Referral.objects.select_for_update().filter(referee=order.user, status=Referral.Status.JOINED).first()
    if referral is None:
        return
    rules = LoyaltySettings.load()
    referral.rewarded_order = order
    if rules.referral_reward <= 0 and rules.referee_reward <= 0:
        referral.status = Referral.Status.NO_REWARD
        referral.save(update_fields=["status", "rewarded_order"])
        return
    for user, amount, text in (
        (referral.referrer, rules.referral_reward, "Referral reward: a friend's first order was delivered"),
        (referral.referee, rules.referee_reward, "Welcome reward for joining with a referral code"),
    ):
        if amount > 0:
            entry = grant(user, K.REFERRAL, amount, reference=order.order_number, description=text, pending=True)
            entry.order = order  # tied to the order: reversed if it is cancelled or returned
            entry.status, entry.available_at = S.ELIGIBLE, release_at
            entry.save(update_fields=["order", "status", "available_at"])
    referral.status = Referral.Status.REWARDED
    referral.save(update_fields=["status", "rewarded_order"])


def on_order_cancelled(order) -> None:
    """Pending credits of the order are reversed; credits used on it come back (original expiry)."""
    CreditEntry.objects.filter(order=order, status__in=CreditEntry.WAITING).update(
        status=S.REVERSED, updated_at=timezone.now()
    )
    restore_for_order(order, reason=f"Order {order.order_number} cancelled")


def on_return_received(
    ret,
    order,
    *,
    returned_credit: Decimal,
    returned_paid: Decimal,
    paid_total: Decimal,
    already_returned: Decimal = ZERO,
) -> None:
    """A refunded return: credits used on the returned items come back, and pending cashback shrinks in
    proportion to what was refunded (it is replaced by a smaller pending entry; nothing is edited)."""
    if returned_credit > 0:
        restore_for_order(order, returned_credit, reason=f"Return {ret.return_number}", return_request=ret)
    kept_before = paid_total - already_returned  # paid goods still with the customer before this return
    if kept_before <= 0:
        return
    keep_share = max(kept_before - returned_paid, ZERO) / kept_before
    if keep_share <= 0:
        # Everything paid for came back: the welcome reward (not yet usable) goes too. A partial return keeps
        # it — the order was still delivered.
        CreditEntry.objects.filter(
            order=order, status__in=CreditEntry.WAITING, kind=K.PROMO, reference__startswith=WELCOME_PREFIX
        ).update(status=S.REVERSED, updated_at=timezone.now())
    for entry in CreditEntry.objects.select_for_update().filter(
        order=order, status__in=CreditEntry.WAITING, kind__in=(K.CASHBACK, K.REFERRAL)
    ):
        new_amount = q(entry.amount * keep_share)
        was = entry.status
        entry.status = S.REVERSED
        entry.save(update_fields=["status", "updated_at"])
        if new_amount > 0:
            replacement = grant(
                entry.user,
                entry.kind,
                new_amount,
                reference=ret.return_number,
                description=f"{entry.description} — reduced after return {ret.return_number}",
                order=order,
                pending=True,
                source=entry,
                return_request=ret,
            )
            replacement.status, replacement.available_at = was, entry.available_at
            replacement.save(update_fields=["status", "available_at"])


def release_due(now=None) -> int:
    """Pending credits whose return window has passed become usable (periodic job). Credits of orders
    that are no longer delivered (cancelled, being returned) wait or were reversed."""
    from apps.orders.models import OrderStatus

    now = now or timezone.now()
    rules = LoyaltySettings.load()
    count = 0
    due = CreditEntry.objects.filter(status=S.ELIGIBLE, available_at__lte=now).select_related("order")
    for entry in list(due[:500]):
        if entry.order is not None and entry.order.status != OrderStatus.DELIVERED:
            continue  # a return in progress decides first
        updated = CreditEntry.objects.filter(pk=entry.pk, status=S.ELIGIBLE).update(
            status=S.AVAILABLE, expires_at=now + timedelta(days=rules.expiry_days), updated_at=now
        )
        count += updated
        if updated:
            from apps.notifications.services import notify

            notify(
                entry.user,
                event="loyalty.credit_available",
                context={
                    "amount": entry.amount,
                    "description": entry.description or entry.get_kind_display(),
                    "expiry_days": rules.expiry_days,
                },
                data={"entry_id": entry.pk},
            )
    return count
