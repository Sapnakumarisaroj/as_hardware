import pytest
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db


def test_jwt_signing_key_is_never_empty():
    assert settings.SIMPLE_JWT["SIGNING_KEY"]


def test_bearer_token_authenticates_api_requests(user):
    client = APIClient()
    assert client.get("/api/cart/").status_code == 401
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get("/api/cart/").status_code == 200
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert client.get("/api/cart/").status_code == 401
