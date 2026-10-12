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
    """A store manager. Assign stores with `store.managers.add(staff_user)`."""
    return _user("staff@example.com", role="store_manager")


@pytest.fixture
def delivery_user(db):
    from apps.delivery.models import DeliveryPartner

    user = _user("rider@example.com", role="delivery_partner", full_name="Ravi Rider", phone="9123456780")
    DeliveryPartner.objects.create(user=user, phone="9123456780")
    return user


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters and login-failure counters live in the cache; isolate tests."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


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


@pytest.fixture(autouse=True)
def _flat_delivery_charges(request):
    """Tests written before distance bands and "first N orders free" expect the flat DELIVERY_FEE.
    Switch both off unless a test asks for the shop defaults (`@pytest.mark.delivery_charges`)."""
    if "django_db" not in request.keywords and "db" not in request.fixturenames:
        yield
        return
    if request.node.get_closest_marker("delivery_charges"):
        yield
        return
    from apps.delivery.models import DeliveryCharges

    request.getfixturevalue("db")
    DeliveryCharges.objects.update_or_create(pk=1, defaults={"distance_bands": [], "free_first_orders": 0})
    yield
