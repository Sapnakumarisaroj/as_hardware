import pytest

pytestmark = pytest.mark.django_db


def test_promise_is_public_and_follows_the_setting(api_client, settings):
    settings.FAST_DELIVERY_MAX_MINUTES = 45
    res = api_client.get("/api/delivery/promise/")
    assert res.status_code == 200
    assert res.json() == {"fast_delivery_max_minutes": 45}
