"""Role-based permissions. The backend is the final authority; the frontend only mirrors these.

Roles (accounts.User.role):
- customer          own data only
- store_manager     inventory + orders of *assigned* stores (Store.managers)
- delivery_partner  own delivery assignments / status / earnings
- admin             everything (superusers count as admin)
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

ADMIN = "admin"
STORE_MANAGER = "store_manager"
DELIVERY_PARTNER = "delivery_partner"
CUSTOMER = "customer"


def _authed(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active)


def is_admin(user) -> bool:
    return _authed(user) and (user.is_superuser or user.role == ADMIN)


def is_store_manager(user) -> bool:
    return _authed(user) and user.role == STORE_MANAGER


def is_delivery_partner(user) -> bool:
    return _authed(user) and user.role == DELIVERY_PARTNER


def is_staff_member(user) -> bool:
    """Operations roles: admins and store managers."""
    return is_admin(user) or is_store_manager(user)


def managed_store_ids(user) -> list[int] | None:
    """Store IDs a user may operate on. `None` means "all stores" (admin); [] means none."""
    if is_admin(user):
        return None
    if is_store_manager(user):
        return list(user.managed_stores.values_list("id", flat=True))
    return []


def scope_to_managed_stores(queryset, user, store_field: str = "store"):
    ids = managed_store_ids(user)
    if ids is None:
        return queryset
    return queryset.filter(**{f"{store_field}__in": ids})


class IsAdminRole(BasePermission):
    message = "Administrator access required."

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsStaffRole(BasePermission):
    """Admin or store manager. Querysets must additionally be scoped with `scope_to_managed_stores`."""

    message = "Store manager access required."

    def has_permission(self, request, view):
        return is_staff_member(request.user)


class IsDeliveryPartner(BasePermission):
    message = "Delivery partner access required."

    def has_permission(self, request, view):
        return is_delivery_partner(request.user) and hasattr(request.user, "delivery_partner")


class IsAdminOrReadOnly(BasePermission):
    """Anyone may read; only admins may write."""

    message = "Administrator access required."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_admin(request.user)
