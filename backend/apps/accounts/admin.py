from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Address, CustomerProfile, User


class CustomerProfileInline(admin.StackedInline):
    model = CustomerProfile
    can_delete = False
    fields = ("preferred_language", "marketing_opt_in", "whatsapp_opt_in", "personalization_opt_in")


class AddressInline(admin.TabularInline):
    model = Address
    fields = ("name", "phone", "address_line1", "city", "postal_code", "address_type", "is_default")
    extra = 0
    show_change_link = True


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("email", "full_name", "phone", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "full_name", "phone")
    inlines = [CustomerProfileInline, AddressInline]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "role", "email_verified", "phone_verified")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "role", "password1", "password2")}),
    )

    def get_inlines(self, request, obj):
        return self.inlines if obj else []


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "city", "postal_code", "address_type", "is_default")
    list_filter = ("address_type", "state", "city")
    search_fields = ("name", "phone", "user__email", "postal_code", "city")
    raw_id_fields = ("user",)
    exclude = ("is_deleted", "deleted_at")
