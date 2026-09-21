"""Role-based permissions. Roles live on `accounts.User.role`; superusers count as admins."""

from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_admin(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or user.role == "admin"))


def is_staff_member(user) -> bool:
    """Admins and store staff (operations roles)."""
    return is_admin(user) or bool(user and user.is_authenticated and user.role == "store_staff")


class IsAdminRole(BasePermission):
    message = "Administrator access required."

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsStaffRole(BasePermission):
    message = "Store staff access required."

    def has_permission(self, request, view):
        return is_staff_member(request.user)


class IsAdminOrReadOnly(BasePermission):
    """Anyone may read; only admins may write."""

    message = "Administrator access required."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_admin(request.user)
