from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_customer_profile(sender, instance, created, **kwargs):
    if created:
        CustomerProfile.objects.get_or_create(user=instance)
