from django.conf import settings
from django.db import models


class BusinessQuestion(models.Model):
    """A question asked to the business assistant and what it answered (the person's own history,
    and a record of which report was read for whom)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_questions")
    question = models.CharField(max_length=300)
    intent = models.CharField(max_length=30, blank=True)
    report = models.CharField(max_length=30, blank=True)
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)
    store_name = models.CharField(max_length=120, blank=True)
    answer = models.TextField(blank=True)
    source = models.CharField(max_length=10, default="rules", help_text="rules | ai (a model routed or reworded it)")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.question[:40]}"
