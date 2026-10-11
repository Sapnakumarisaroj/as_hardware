"""Picture import from a folder + mapping sheet, and the 'unverified picture' publishing guard."""

import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from PIL import Image

from apps.catalog import services
from apps.catalog.image_import import import_images
from apps.catalog.importer import read_table
from apps.catalog.models import ProductImage
from apps.core.exceptions import ServiceError
from apps.core.testing import create_product

pytestmark = pytest.mark.django_db


def _picture(path, colour="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), colour).save(path, format="PNG")
    return path


def _png(colour="white") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="PNG")
    return SimpleUploadedFile("photo.png", buffer.getvalue(), content_type="image/png")


def _sheet(*rows: str, header="product_sku,file,is_primary,source_type") -> object:
    return read_table(("\n".join([header, *rows]) + "\n").encode(), "map.csv", check_header=False)


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return tmp_path


@pytest.fixture
def draft():
    product, _ = create_product(name="Fevicol SH", published=False)
    return product


def test_dry_run_checks_without_storing(media, draft):
    _picture(media / "pics" / "Glue" / "sh.png")
    report = import_images(_sheet(f"{draft.sku},Glue/sh.png,yes,"), media / "pics", dry_run=True)
    assert report.ok, report.errors
    assert report.counts == {"added": 1, "already_there": 0} and not report.committed
    assert not draft.images.exists()
    assert not (media / "media").exists()  # no file written for a dry run


def test_commit_adds_unverified_by_default_and_a_rerun_adds_nothing(media, draft):
    _picture(media / "pics" / "sh.png")
    _picture(media / "pics" / "sh-back.png", "black")
    table = _sheet(f"{draft.sku},sh.png,yes,", f"{draft.sku},sh-back.png,no,")
    report = import_images(table, media / "pics", dry_run=False)
    assert report.committed and report.counts["added"] == 2, report.errors
    images = list(draft.images.order_by("sort_order"))
    assert [i.source_type for i in images] == ["unverified", "unverified"]
    assert [i.is_primary for i in images] == [True, False]
    assert images[0].alt_text == "Fevicol SH"

    again = import_images(table, media / "pics", dry_run=False)
    assert again.counts == {"added": 0, "already_there": 2}
    assert draft.images.count() == 2


def test_same_picture_for_two_products_is_refused(media, draft):
    other, _ = create_product(name="Fevicol Marine", published=False)
    _picture(media / "pics" / "a.png")
    _picture(media / "pics" / "copy-of-a.png")  # byte-identical
    report = import_images(
        _sheet(f"{draft.sku},a.png,yes,", f"{other.sku},copy-of-a.png,yes,"), media / "pics", dry_run=False
    )
    assert not report.ok
    assert "listed for" in report.errors[0]["message"]
    assert not ProductImage.objects.exists()


@pytest.mark.parametrize(
    "row, column",
    [
        ("NOPE,a.png,yes,", "product_sku"),
        ("{sku},missing.png,yes,", "file"),
        ("{sku},../outside.png,yes,", "file"),
        ("{sku},a.png,maybe,", "is_primary"),
        ("{sku},a.png,yes,stolen", "source_type"),
    ],
)
def test_bad_rows_are_reported_and_nothing_is_saved(media, draft, row, column):
    _picture(media / "pics" / "a.png")
    _picture(media / "outside.png")
    report = import_images(_sheet(row.format(sku=draft.sku)), media / "pics", dry_run=False)
    assert [e["column"] for e in report.errors] == [column]
    assert not draft.images.exists()


def test_live_product_refuses_an_unverified_picture(media):
    live, _ = create_product(name="Live Glue", published=True)
    _picture(media / "pics" / "a.png")
    report = import_images(_sheet(f"{live.sku},a.png,yes,"), media / "pics", dry_run=True)
    assert "unverified" in report.errors[0]["message"]
    with pytest.raises(ServiceError):
        services.add_product_image(live, _png(), source_type=ProductImage.SourceType.UNVERIFIED)


def test_command_dry_run_and_commit(media, draft, tmp_path):
    _picture(media / "pics" / "sh.png")
    sheet = tmp_path / "map.csv"
    sheet.write_text(f"product_sku,file\n{draft.sku},sh.png\n", encoding="utf-8")
    call_command("import_product_images", str(sheet), "--root", str(media / "pics"))
    assert not draft.images.exists()
    call_command("import_product_images", str(sheet), "--root", str(media / "pics"), "--commit")
    assert draft.images.get().source_type == "unverified"
    sheet.write_text("product_sku,file\nNOPE,sh.png\n", encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("import_product_images", str(sheet), "--root", str(media / "pics"), "--commit")


# --- Publishing guard ------------------------------------------------------------------------------


def test_a_product_with_an_unverified_picture_cannot_be_published(media, draft):
    services.add_product_image(draft, _png(), source_type=ProductImage.SourceType.UNVERIFIED)
    draft.is_published = True
    with pytest.raises(ValidationError) as excinfo:
        draft.full_clean()  # what the Django admin runs, including its list "published" checkbox
    assert "is_published" in excinfo.value.message_dict
    draft.refresh_from_db()
    with pytest.raises(ValidationError):
        services.save_product(instance=draft, data={"is_published": True})

    # Once the picture's source is recorded, the guard no longer applies.
    draft.refresh_from_db()
    draft.images.update(source_type=ProductImage.SourceType.MANUFACTURER)
    services.save_product(instance=draft, data={"is_published": True})
    draft.refresh_from_db()
    assert draft.is_published


def test_publishing_through_the_dashboard_is_refused(media, admin_client, draft):
    services.add_product_image(draft, _png(), source_type=ProductImage.SourceType.UNVERIFIED)
    res = admin_client.patch(f"/api/admin/products/{draft.pk}/", {"is_published": True}, format="json")
    assert res.status_code == 400, res.content
    draft.refresh_from_db()
    assert not draft.is_published
