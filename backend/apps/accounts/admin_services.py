"""Administrator-only user management. Roles are never changed anywhere else."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.core.audit import record_audit
from apps.core.exceptions import ConflictError, ServiceError

from .auth_services import _set_active

User = get_user_model()


class UserManagementError(ServiceError):
    default_code = "user_management_error"


@transaction.atomic
def update_user(target, *, actor, request=None, **data):
    """Allowed keys: role, is_active, full_name, phone (already validated/normalised), managed_store_ids."""
    target = User.objects.select_for_update().get(pk=target.pk)
    if target.pk == actor.pk and ("role" in data or data.get("is_active") is False):
        raise UserManagementError(
            "You cannot change your own role or deactivate your own account.", code="self_modification"
        )

    # Personal values are never copied into the audit log, only which fields changed.
    changes = {}
    if "full_name" in data and data["full_name"] != target.full_name:
        target.full_name = data["full_name"]
        changes["full_name"] = "updated"
    if "phone" in data and (data["phone"] or None) != target.phone:
        target.phone = data["phone"] or None
        changes["phone"] = "updated"

    new_role = data.get("role", target.role)
    if new_role != target.role:
        changes["role"] = {"from": target.role, "to": new_role}
        target.role = new_role
        target.is_staff = target.is_superuser or new_role == User.Role.ADMIN  # Django-admin access
    try:
        with transaction.atomic():
            target.save()
    except IntegrityError as exc:
        raise ConflictError("That phone number is already used by another account.", code="phone_in_use") from exc

    if new_role == User.Role.DELIVERY_PARTNER:
        _ensure_delivery_profile(target)

    if new_role == User.Role.STORE_MANAGER:
        if "managed_store_ids" in data:
            _set_managed_stores(target, data["managed_store_ids"], changes)
    else:
        if data.get("managed_store_ids"):
            raise UserManagementError("Only store managers can be assigned to stores.", code="invalid_assignment")
        if target.managed_stores.exists():
            target.managed_stores.clear()
            changes["managed_stores"] = "cleared"

    if changes:
        action = "user.role_change" if "role" in changes else "user.update"
        record_audit(action=action, actor=actor, target=target, request=request, changes=changes)

    if "is_active" in data and data["is_active"] != target.is_active:
        _set_active(target, data["is_active"], actor=actor, request=request)
    return target


def _ensure_delivery_profile(user) -> None:
    from apps.delivery.models import DeliveryPartner

    if hasattr(user, "delivery_partner"):
        return
    if not user.phone:
        raise UserManagementError("Add a phone number before making someone a delivery partner.", code="phone_required")
    DeliveryPartner.objects.create(user=user, phone=user.phone)


def _set_managed_stores(user, store_ids, changes) -> None:
    from apps.stores.models import Store

    stores = list(Store.objects.filter(pk__in=store_ids))
    if len(stores) != len(set(store_ids)):
        raise UserManagementError("One or more stores do not exist.", code="invalid_store")
    user.managed_stores.set(stores)
    changes["managed_stores"] = sorted(s.pk for s in stores)
