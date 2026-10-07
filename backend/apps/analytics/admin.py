from django.contrib import admin

from .models import BusinessQuestion


@admin.register(BusinessQuestion)
class BusinessQuestionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "question", "report", "source")
    list_filter = ("report", "source")
    search_fields = ("question", "user__email")
    readonly_fields = [f.name for f in BusinessQuestion._meta.fields]

    def has_add_permission(self, request):
        return False
