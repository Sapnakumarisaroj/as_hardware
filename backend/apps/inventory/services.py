"""The only code allowed to change stock. Every change locks the inventory row, validates,
updates quantities and appends a StockMovement in one transaction."""

from django.db import transaction
from django.db.models import Sum

from apps.core.exceptions import ServiceError

from .models import Inventory, StockMovement

Type = StockMovement.Type


class InsufficientStock(ServiceError):
    status_code = 409
    default_code = "insufficient_stock"
    default_detail = "Not enough stock available."


@transaction.atomic
def apply_movement(
    inventory: Inventory,
    movement_type: str,
    quantity: int,
    *,
    reason: str = "",
    reference_type: str = "",
    reference_id: str = "",
    actor=None,
) -> StockMovement:
    if movement_type != Type.ADJUSTMENT and quantity <= 0:
        raise ServiceError("Quantity must be a positive whole number.", code="invalid_quantity")
    if movement_type == Type.ADJUSTMENT and quantity == 0:
        raise ServiceError("Adjustment quantity cannot be zero.", code="invalid_quantity")
    if movement_type == Type.ADJUSTMENT and not reason.strip():
        raise ServiceError("A reason is required for manual adjustments.", code="reason_required")

    inv = Inventory.objects.select_for_update().get(pk=inventory.pk)
    available, reserved = inv.available_quantity, inv.reserved_quantity

    if movement_type in (Type.PURCHASE, Type.RETURN):
        available += quantity
    elif movement_type == Type.ADJUSTMENT:
        available += quantity
    elif movement_type == Type.RESERVATION:
        available -= quantity
        reserved += quantity
    elif movement_type == Type.RELEASE:
        reserved -= quantity
        available += quantity
    elif movement_type == Type.SALE:
        reserved -= quantity
    else:
        raise ServiceError(f"Unknown movement type '{movement_type}'.", code="invalid_movement")

    if available < 0:
        raise InsufficientStock(
            f"Only {inv.available_quantity} unit(s) of {inv.variant.sku} available at {inv.store.code}.",
            details={"sku": inv.variant.sku, "available": inv.available_quantity},
        )
    if reserved < 0:
        raise ServiceError("Cannot release or sell more than is reserved.", code="invalid_reservation")

    inv.available_quantity, inv.reserved_quantity = available, reserved
    inv.save(update_fields=["available_quantity", "reserved_quantity", "updated_at"])
    inventory.available_quantity, inventory.reserved_quantity = available, reserved
    return StockMovement.objects.create(
        inventory=inv,
        movement_type=movement_type,
        quantity=quantity,
        available_after=available,
        reserved_after=reserved,
        reason=reason,
        reference_type=reference_type,
        reference_id=str(reference_id),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


def total_available(variant_id: int) -> int:
    """Sellable units across all active, order-accepting fulfillment stores."""
    from apps.stores.models import Store

    result = Inventory.objects.filter(
        variant_id=variant_id,
        is_active=True,
        store__is_active=True,
        store__is_deleted=False,
        store__accepts_orders=True,
        store__kind__in=Store.FULFILLMENT_KINDS,
    ).aggregate(total=Sum("available_quantity"))
    return result["total"] or 0
