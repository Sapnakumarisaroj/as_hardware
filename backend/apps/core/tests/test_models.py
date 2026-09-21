import pytest
from django.contrib.auth import get_user_model

from apps.core.audit import record_audit
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db


def test_record_audit(rf):
    user = get_user_model().objects.create_user("admin@example.com", "x-Strong-pass-1")
    req = rf.get("/", REMOTE_ADDR="10.0.0.5")
    entry = record_audit(action="user.update", actor=user, target=user, changes={"role": "admin"}, request=req)
    assert entry.target_type == "accounts.user"
    assert entry.target_id == str(user.pk)
    assert entry.ip_address == "10.0.0.5"
    assert AuditLog.objects.count() == 1
