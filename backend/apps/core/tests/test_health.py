from unittest import mock

import pytest
from django.db.utils import OperationalError
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_health_ok(api_client):
    res = api_client.get(reverse("health"))
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["app"]


def test_health_reports_db_failure(api_client):
    with mock.patch("apps.core.views.connection.cursor", side_effect=OperationalError("down")):
        res = api_client.get(reverse("health"))
    assert res.status_code == 503
    assert res.json()["database"] == "unavailable"


def test_request_id_generated_and_echoed(api_client):
    res = api_client.get(reverse("health"))
    assert len(res["X-Request-ID"]) == 32

    res = api_client.get(reverse("health"), HTTP_X_REQUEST_ID="client-abc_123")
    assert res["X-Request-ID"] == "client-abc_123"


def test_malformed_request_id_is_replaced(api_client):
    res = api_client.get(reverse("health"), HTTP_X_REQUEST_ID="bad id<script>")
    assert res["X-Request-ID"] != "bad id<script>"


def test_openapi_schema_available(api_client):
    res = api_client.get("/api/schema/?format=json")
    assert res.status_code == 200
    assert "/api/health/" in res.json()["paths"]
