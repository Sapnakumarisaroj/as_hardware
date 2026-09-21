"""Address workflows. Owns the "exactly one default address per user" rule, which is
enforced here under a row lock because MySQL/MariaDB lack partial unique indexes."""

from django.db import transaction

from apps.core.validators import normalize_phone

from .models import Address


def _lock_user_addresses(user):
    return list(Address.objects.select_for_update().filter(user=user).order_by("id"))


@transaction.atomic
def create_address(*, user, **data) -> Address:
    existing = _lock_user_addresses(user)
    data["phone"] = normalize_phone(data.get("phone", ""))
    make_default = data.pop("is_default", False) or not existing
    address = Address.objects.create(user=user, is_default=False, **data)
    if make_default:
        _make_default(user, address)
    return address


@transaction.atomic
def update_address(address: Address, **data) -> Address:
    _lock_user_addresses(address.user)
    make_default = data.pop("is_default", None)
    if "phone" in data:
        data["phone"] = normalize_phone(data["phone"])
    for field, value in data.items():
        setattr(address, field, value)
    address.save()
    if make_default:
        _make_default(address.user, address)
    return address


@transaction.atomic
def set_default_address(address: Address) -> Address:
    _lock_user_addresses(address.user)
    _make_default(address.user, address)
    return address


@transaction.atomic
def delete_address(address: Address) -> None:
    """Soft delete; if it was the default, promote the most recently updated remaining address."""
    _lock_user_addresses(address.user)
    was_default = address.is_default
    address.is_default = False
    address.save(update_fields=["is_default", "updated_at"])
    address.delete()
    if was_default:
        replacement = Address.objects.filter(user=address.user).order_by("-updated_at").first()
        if replacement:
            _make_default(address.user, replacement)


def _make_default(user, address: Address) -> None:
    Address.objects.filter(user=user, is_default=True).exclude(pk=address.pk).update(is_default=False)
    if not address.is_default:
        address.is_default = True
        address.save(update_fields=["is_default", "updated_at"])
