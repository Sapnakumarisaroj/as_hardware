"""Data foundation for AI features (no AI logic in Phase 2).

- AIConversation / AIMessage: assistant, voice and image-search sessions. `product_refs`
  stores the catalog IDs the assistant actually showed, so answers are auditable.
- Project / ProjectItem: saved project kits (e.g. "Paint 10x12 room") built from real variants.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class AIConversation(TimeStampedModel):
    class Kind(models.TextChoices):
        ASSISTANT = "assistant", "Hardware assistant"
        VOICE = "voice", "Voice shopping"
        IMAGE = "image", "Image search"
        PROJECT = "project", "Project builder"
        BUSINESS = "business", "Business assistant (admin)"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="ai_conversations"
    )
    session_key = models.CharField(max_length=64, blank=True, db_index=True, help_text="For guest sessions.")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ASSISTANT)
    language = models.CharField(max_length=10, default="en")
    title = models.CharField(max_length=150, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "kind", "-updated_at"])]

    def __str__(self) -> str:
        return self.title or f"{self.kind} #{self.pk}"


class AIMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        TOOL = "tool", "Tool result"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    tool_calls = models.JSONField(default=list, blank=True)
    product_refs = models.JSONField(default=list, blank=True, help_text="Variant/product IDs shown to the customer.")
    # Phase 12: the structured parts of an assistant answer (intent, questions, actions, safety,
    # estimate, ai_mode), so a conversation is shown again exactly as it was answered.
    payload = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=80, blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"


class Project(TimeStampedModel):
    class Type(models.TextChoices):
        PAINTING = "painting", "Painting"
        BATHROOM_REPAIR = "bathroom_repair", "Bathroom repair"
        PLUMBING = "plumbing", "Plumbing"
        ELECTRICAL = "electrical", "Electrical work"
        WALL_DRILLING = "wall_drilling", "Wall drilling"
        FURNITURE_REPAIR = "furniture_repair", "Furniture installation / repair"
        GARDENING = "gardening", "Gardening"
        CONSTRUCTION = "construction", "Basic construction"
        WATERPROOFING = "waterproofing", "Waterproofing"
        TILING = "tiling", "Tiling"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (collecting details)"
        READY = "ready", "Kit ready"
        ORDERED = "ordered", "Added to cart / ordered"
        ARCHIVED = "archived", "Archived"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects")
    conversation = models.ForeignKey(
        AIConversation, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    project_type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=150)
    inputs = models.JSONField(default=dict, blank=True, help_text="Answers collected, e.g. room dimensions.")
    safety_notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self) -> str:
        return self.title


class ProjectItem(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    label = models.CharField(max_length=150, help_text="What is needed, e.g. 'Interior emulsion paint'.")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    unit = models.CharField(max_length=10, blank=True)
    is_optional = models.BooleanField(default=False)
    is_estimate = models.BooleanField(default=True, help_text="Calculated quantities are estimates; shown as such.")
    rationale = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    # Phase 19 (project builder): which material of the project template this line is, whether it is in
    # the kit, whether the customer changed it (kept when recommendations are regenerated), and the
    # estimate behind it (need amount and unit, search words, reasons).
    material_key = models.CharField(max_length=40, blank=True)
    included = models.BooleanField(default=True)
    customer_set = models.BooleanField(default=False)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.quantity} {self.unit} {self.label}"
