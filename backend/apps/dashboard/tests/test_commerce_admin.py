"""Phase 15 dashboard: bulk prices and options in the product form, option types, curated lists,
free-delivery rules, COD switches — and who may see or change them."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.catalog.models import Collection, OptionType, ProductVariant
from apps.core.testing import create_category, create_product, create_store
from apps.delivery.models import DeliveryZone

pytestmark = pytest.mark.django_db

NEW_ADMIN_URLS = [
    "/api/admin/option-types/",
    "/api/admin/collections/",
    "/api/admin/free-delivery-rules/",
    "/api/admin/payment-settings/",
]


@pytest.mark.parametrize("url", NEW_ADMIN_URLS)
def test_visitors_and_customers_are_kept_out(api_client, auth_client, url):
    assert api_client.get(url).status_code == 401
    assert auth_client.get(url).status_code == 403
    assert auth_client.post(url, {}, format="json").status_code in (403, 405)


def test_store_managers_read_options_and_cod_settings_but_change_nothing(staff_client):
    assert staff_client.get("/api/admin/option-types/").status_code == 200
    assert staff_client.get("/api/admin/payment-settings/").status_code == 200
    assert staff_client.post("/api/admin/option-types/", {"name": "Grade"}, format="json").status_code == 403
    assert staff_client.get("/api/admin/collections/").status_code == 403
    assert staff_client.post("/api/admin/collections/", {"name": "X"}, format="json").status_code == 403
    assert staff_client.get("/api/admin/free-delivery-rules/").status_code == 403


def test_session_lists_the_new_sections_for_admins_only(admin_client, staff_client):
    sections = admin_client.get("/api/admin/session/").json()["sections"]
    assert {"options", "collections", "free-delivery", "payment-settings"} <= set(sections)
    assert "collections" not in staff_client.get("/api/admin/session/").json()["sections"]


def test_option_types_crud(admin_client):
    cement = create_category("Cement")
    created = admin_client.post(
        "/api/admin/option-types/",
        {"name": "Grade", "categories": [cement.id], "value_list": [{"value": "53 Grade"}, {"value": "43 Grade"}]},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert [v["value"] for v in created.data["values"]] == ["53 Grade", "43 Grade"]
    assert admin_client.post("/api/admin/option-types/", {"name": "grade"}, format="json").status_code == 400
    option = OptionType.objects.get(name="Grade")
    first = option.values.get(value="53 Grade")
    renamed = admin_client.patch(
        f"/api/admin/option-types/{option.id}/",
        {"value_list": [{"id": first.id, "value": "OPC 53"}, {"value": "PPC"}]},
        format="json",
    )
    assert renamed.status_code == 200, renamed.data
    assert [v["value"] for v in renamed.data["values"]] == ["OPC 53", "PPC"]
    assert option.values.filter(pk=first.pk, slug="opc-53").exists()  # same row, so variants follow the rename


def test_product_form_saves_tiers_and_options_and_refuses_bad_ones(admin_client):
    cement = create_category("Cement")
    grade = OptionType.objects.create(name="Grade")
    grade.categories.set([cement])
    payload = {
        "name": "OPC Cement",
        "sku": "OPC-1",
        "category": cement.id,
        "is_published": True,
        "variants": [
            {
                "sku": "OPC-53",
                "mrp": "480",
                "price": "450",
                "price_tiers": [{"min_quantity": 10, "unit_price": "415"}, {"min_quantity": 30, "unit_price": "405"}],
                "options": [{"option_type": grade.id, "value": "53 Grade"}],
            }
        ],
    }
    created = admin_client.post("/api/admin/products/", payload, format="json")
    assert created.status_code == 201, created.data
    variant = created.data["variants"][0]
    assert variant["price_tiers"] == [
        {"min_quantity": 10, "unit_price": "415.00"},
        {"min_quantity": 30, "unit_price": "405.00"},
    ]
    assert variant["options"][0]["value"] == "53 Grade" and variant["attributes"] == {"Grade": "53 Grade"}
    assert created.data["option_types"][0]["name"] == "Grade"

    url = f"/api/admin/products/{created.data['id']}/"
    overlapping = admin_client.patch(
        url,
        {"variants": [{"id": variant["id"], "price_tiers": [
            {"min_quantity": 10, "unit_price": "415"}, {"min_quantity": 10, "unit_price": "400"}]}]},
        format="json",
    )  # fmt: skip
    assert overlapping.status_code == 400 and overlapping.json()["error"]["code"] == "overlapping_tiers"
    above_mrp = admin_client.patch(
        url, {"variants": [{"id": variant["id"], "price_tiers": [{"min_quantity": 5, "unit_price": "500"}]}]},
        format="json",
    )  # fmt: skip
    assert above_mrp.status_code == 400 and above_mrp.json()["error"]["code"] == "tier_above_mrp"
    dearer = admin_client.patch(
        url,
        {"variants": [{"id": variant["id"], "price_tiers": [
            {"min_quantity": 5, "unit_price": "420"}, {"min_quantity": 20, "unit_price": "430"}]}]},
        format="json",
    )  # fmt: skip
    assert dearer.status_code == 400 and dearer.json()["error"]["code"] == "tier_not_cheaper"
    negative = admin_client.patch(url, {"variants": [{"id": variant["id"], "mrp": "-1"}]}, format="json")
    assert negative.status_code == 400
    assert ProductVariant.objects.get(pk=variant["id"]).price_tiers.count() == 2  # nothing half-saved

    tools = create_category("Tools")
    wrong_option = admin_client.post(
        "/api/admin/products/",
        {**payload, "sku": "HAM-1", "category": tools.id,
         "variants": [{**payload["variants"][0], "sku": "HAM-1A", "price_tiers": []}]},
        format="json",
    )  # fmt: skip
    assert wrong_option.status_code == 400 and wrong_option.json()["error"]["code"] == "invalid_option"


def test_collections_crud_and_preview(admin_client):
    _, drill = create_product(name="Drill")
    _, saw = create_product(name="Saw")
    created = admin_client.post(
        "/api/admin/collections/",
        {"name": "Deals of the week", "product_ids": [saw.product_id, drill.product_id],
         "ends_at": (timezone.now() + timedelta(days=7)).isoformat()},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.data
    assert [i["name"] for i in created.data["items"]] == ["Saw", "Drill"] and created.data["state"] == "live"
    preview = admin_client.get(f"/api/admin/collections/{created.data['id']}/preview/").json()
    assert preview["count"] == 2 and preview["is_live"]
    assert admin_client.post("/api/admin/collections/", {"name": "Empty manual"}, format="json").status_code == 400
    auto = admin_client.post(
        "/api/admin/collections/", {"name": "Best sellers", "rule": "best_sellers", "window_days": 30}, format="json"
    )
    assert auto.status_code == 201 and auto.data["rule"] == "best_sellers"
    bad_dates = admin_client.patch(
        f"/api/admin/collections/{created.data['id']}/",
        {"starts_at": timezone.now().isoformat(), "ends_at": (timezone.now() - timedelta(days=1)).isoformat()},
        format="json",
    )
    assert bad_dates.status_code == 400
    assert admin_client.delete(f"/api/admin/collections/{auto.data['id']}/").status_code == 204
    assert Collection.objects.count() == 1


def test_cod_switches_on_stores_and_zones(admin_client, staff_client, staff_user):
    store = create_store()
    store.managers.add(staff_user)
    zone = DeliveryZone.objects.get(store=store)
    # A store manager runs the store day to day but doesn't decide payment methods.
    refused = staff_client.patch(f"/api/admin/stores/{store.id}/", {"cod_enabled": False}, format="json")
    assert refused.status_code == 403
    changed = admin_client.patch(f"/api/admin/stores/{store.id}/", {"cod_enabled": False}, format="json")
    assert changed.status_code == 200 and changed.json()["cod_enabled"] is False
    zone_changed = admin_client.patch(f"/api/admin/zones/{zone.id}/", {"cod_enabled": False}, format="json")
    assert zone_changed.status_code == 200 and zone_changed.json()["cod_enabled"] is False
    settings = admin_client.get("/api/admin/payment-settings/").json()
    assert [s["id"] for s in settings["stores_without_cod"]] == [store.id]
    assert [z["id"] for z in settings["zones_without_cod"]] == [zone.id]
