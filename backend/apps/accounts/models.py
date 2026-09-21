"""Users, customer profiles and delivery addresses.

The custom User was defined in Phase 1 so the very first migration uses it.
"""

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeleteModel, TimeStampedModel
from apps.core.validators import phone_validator, postal_code_validator


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STORE_STAFF = "store_staff", "Store staff"
        DELIVERY_PARTNER = "delivery_partner", "Delivery partner"
        ADMIN = "admin", "Admin"

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        # Case-insensitive uniqueness that works on every DB vendor (MariaDB has no functional
        # indexes): always store lowercase, and let the plain unique index do the rest.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN

    def get_full_name(self) -> str:
        return self.full_name or self.email

    def get_short_name(self) -> str:
        return (self.full_name or self.email).split(" ")[0]


class CustomerProfile(TimeStampedModel):
    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        HINDI = "hi", "Hindi"
        HINGLISH = "hi-latn", "Hinglish"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    preferred_language = models.CharField(max_length=10, choices=Language.choices, default=Language.ENGLISH)
    marketing_opt_in = models.BooleanField(default=False)
    whatsapp_opt_in = models.BooleanField(default=False)
    # Recommendation personalisation uses browsing/purchase history only when this is on.
    personalization_opt_in = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"Profile<{self.user_id}>"


class Address(SoftDeleteModel):
    """A delivery address. Orders copy it into a snapshot, so edits never alter past orders."""

    class AddressType(models.TextChoices):
        HOME = "home", "Home"
        WORK = "work", "Work"
        SITE = "site", "Site / project"
        OTHER = "other", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    area = models.CharField(max_length=120, blank=True)
    landmark = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    postal_code = models.CharField(max_length=6, validators=[postal_code_validator])
    country = models.CharField(max_length=2, default="IN")
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    address_type = models.CharField(max_length=10, choices=AddressType.choices, default=AddressType.HOME)
    # "One default per user" is enforced by accounts.services (MySQL has no partial unique indexes).
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_deleted", "is_default"]),
            models.Index(fields=["postal_code"]),
        ]
        verbose_name_plural = "addresses"

    def __str__(self) -> str:
        return f"{self.name}, {self.address_line1}, {self.city} {self.postal_code}"

    def snapshot(self) -> dict:
        """Immutable copy stored on orders."""
        return {
            "name": self.name,
            "phone": self.phone,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "area": self.area,
            "landmark": self.landmark,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
            "latitude": str(self.latitude) if self.latitude is not None else None,
            "longitude": str(self.longitude) if self.longitude is not None else None,
            "address_type": self.address_type,
        }
