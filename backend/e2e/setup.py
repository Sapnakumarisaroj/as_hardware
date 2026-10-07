# E2E setup (Phase 26): staff accounts on a COPY of a seeded database (customers register through the API).
# Refuses to run unless the database file name contains "e2e", so it can't touch a real shop.
from django.contrib.auth import get_user_model
from django.db import connection

from apps.delivery.models import DeliveryPartner
from apps.stores.models import Store

assert "e2e" in str(connection.settings_dict["NAME"]), connection.settings_dict["NAME"]
User = get_user_model()
PASSWORD = "E2e-check-26!"  # noqa: S105 — test accounts on a database copy
kothrud = Store.objects.get(code="DEMO-PUN-KTH")
baner = Store.objects.get(code="DEMO-PUN-BNR")


def user(email, **extra):
    return User.objects.filter(email=email).first() or User.objects.create_user(email, PASSWORD, **extra)


user("e2e-admin@example.com", role="admin", full_name="E2E Admin")
k = user("e2e-mgr-k@example.com", role="store_manager", full_name="Kothrud Manager")
kothrud.managers.add(k)
b = user("e2e-mgr-b@example.com", role="store_manager", full_name="Baner Manager")
baner.managers.add(b)
for i, name in enumerate(("Ravi Rider", "Meera Rider"), start=1):
    r = user(f"e2e-rider{i}@example.com", role="delivery_partner", full_name=name, phone=f"91234567{80 + i}")
    DeliveryPartner.objects.get_or_create(
        user=r, defaults={"phone": f"91234567{80 + i}", "home_store": kothrud, "status": "offline", "is_verified": True}
    )
print("setup ok", kothrud.pk, baner.pk, kothrud.latitude, kothrud.longitude)
