from django.contrib import admin
from django.utils import timezone

from .models import AuditLog, Job
from .permissions import is_admin


class AdminRoleRequiredMixin:
    """Django-admin pages for the catalogue and stock: only active staff accounts with the admin role
    (or superusers) get in, on top of Django's own model permissions. Checked on every request, so a
    store manager or customer who was given `is_staff` or a model permission by mistake still can't
    view or change anything here."""

    def _admin_role(self, request) -> bool:
        return bool(request.user.is_staff and is_admin(request.user))

    def has_module_permission(self, request):
        return self._admin_role(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._admin_role(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request, *args):
        return self._admin_role(request) and super().has_add_permission(request, *args)

    def has_change_permission(self, request, obj=None):
        return self._admin_role(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._admin_role(request) and super().has_delete_permission(request, obj)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "attempts", "run_after", "finished_at", "created_at")
    list_filter = ("status", "name")
    search_fields = ("name", "dedupe_key", "last_error")
    readonly_fields = [f.name for f in Job._meta.fields]
    actions = ["requeue"]

    @admin.action(description="Run failed jobs again")
    def requeue(self, request, queryset):
        count = queryset.filter(status=Job.Status.FAILED).update(
            status=Job.Status.QUEUED, attempts=0, run_after=timezone.now(), finished_at=None
        )
        self.message_user(request, f"{count} job(s) queued again.")

    def has_add_permission(self, request):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_type", "target_id", "ip_address")
    list_filter = ("action", "target_type")
    search_fields = ("action", "target_id", "request_id")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
