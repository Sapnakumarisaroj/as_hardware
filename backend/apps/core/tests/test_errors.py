import pytest
from django.urls import path
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.core.exceptions import ServiceError


class _Input(serializers.Serializer):
    qty = serializers.IntegerField(min_value=1)


class _View(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        kind = request.query_params.get("kind")
        if kind == "service":
            raise ServiceError("Out of stock.", code="out_of_stock", details={"sku": "X1"})
        if kind == "crash":
            raise RuntimeError("secret internal detail")
        _Input(data=request.data).is_valid(raise_exception=True)
        return None


urlpatterns = [path("t/", _View.as_view())]


@pytest.fixture(autouse=True)
def _urls(settings):
    settings.ROOT_URLCONF = __name__


def test_validation_error_envelope(api_client):
    res = api_client.post("/t/", {"qty": 0}, format="json")
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "validation_error"
    assert "qty" in err["details"]
    assert res.json()["request_id"]


def test_service_error_envelope(api_client):
    res = api_client.post("/t/?kind=service", {}, format="json")
    assert res.status_code == 400
    assert res.json()["error"] == {"code": "out_of_stock", "message": "Out of stock.", "details": {"sku": "X1"}}


def test_unhandled_error_does_not_leak(api_client):
    res = api_client.post("/t/?kind=crash", {}, format="json")
    assert res.status_code == 500
    assert "secret" not in res.content.decode()
    assert res.json()["error"]["code"] == "server_error"


def test_unauthenticated_default_is_denied(api_client, settings):
    # Default permission is IsAuthenticated: any endpoint not opting out must reject anonymous users.
    from rest_framework.permissions import IsAuthenticated

    _View.permission_classes = [IsAuthenticated]
    try:
        res = api_client.post("/t/", {"qty": 1}, format="json")
    finally:
        _View.permission_classes = [AllowAny]
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "not_authenticated"
