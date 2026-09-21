import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _user(email: str, **extra):
    return get_user_model().objects.create_user(email, "S3cure-pass!", **extra)


@pytest.fixture
def user(db):
    return _user("customer@example.com", full_name="Asha Kumar")


@pytest.fixture
def other_user(db):
    return _user("other@example.com", full_name="Ravi Shah")


@pytest.fixture
def admin_user(db):
    return _user("admin@example.com", role="admin")


@pytest.fixture
def staff_user(db):
    return _user("staff@example.com", role="store_staff")


@pytest.fixture
def auth_client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def admin_client(admin_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(admin_user)
    return client


@pytest.fixture
def staff_client(staff_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(staff_user)
    return client
