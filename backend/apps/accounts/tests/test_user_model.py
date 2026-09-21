import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_create_user_normalises_email_and_hashes_password():
    u = User.objects.create_user("Jane@Example.COM", "S3cure-pass!")
    assert u.email == "jane@example.com"
    assert u.role == User.Role.CUSTOMER
    assert u.check_password("S3cure-pass!")
    assert u.password != "S3cure-pass!"


def test_email_unique_case_insensitive():
    User.objects.create_user("a@example.com", "S3cure-pass!")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(email="A@example.com")


def test_create_superuser_is_admin_role():
    su = User.objects.create_superuser("root@example.com", "S3cure-pass!")
    assert su.is_staff and su.is_superuser
    assert su.role == User.Role.ADMIN


def test_email_required():
    with pytest.raises(ValueError):
        User.objects.create_user("", "x")
