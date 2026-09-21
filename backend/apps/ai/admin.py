from django.contrib import admin

from .models import AIConversation, AIMessage, Project, ProjectItem


class AIMessageInline(admin.TabularInline):
    model = AIMessage
    fields = ("created_at", "role", "content", "product_refs", "provider", "model")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "user", "language", "title", "updated_at")
    list_filter = ("kind", "language")
    search_fields = ("title", "user__email")
    raw_id_fields = ("user",)
    inlines = [AIMessageInline]


class ProjectItemInline(admin.TabularInline):
    model = ProjectItem
    fields = ("label", "variant", "quantity", "unit", "is_optional", "is_estimate", "sort_order")
    raw_id_fields = ("variant",)
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "project_type", "user", "status", "updated_at")
    list_filter = ("project_type", "status")
    search_fields = ("title", "user__email")
    raw_id_fields = ("user", "conversation")
    inlines = [ProjectItemInline]
