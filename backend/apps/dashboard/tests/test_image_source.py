import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog.models import ProductImage
from apps.core.testing import create_product

pytestmark = pytest.mark.django_db


def _png() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    return SimpleUploadedFile("photo.png", buffer.getvalue(), content_type="image/png")


def test_upload_records_where_the_picture_came_from(admin_client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    product, _ = create_product()
    res = admin_client.post(
        f"/api/admin/products/{product.pk}/images/",
        {
            "image": _png(),
            "source_type": "licensed",
            "image_type": "photo",
            "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
            "licence": "CC BY-SA 4.0, A. Author",
        },
        format="multipart",
    )
    assert res.status_code == 201, res.content
    image = ProductImage.objects.get(product=product)
    assert (image.source_type, image.image_type, image.licence) == ("licensed", "photo", "CC BY-SA 4.0, A. Author")
    assert image.source_url == "https://commons.wikimedia.org/wiki/File:Example.jpg"

    res = admin_client.patch(
        f"/api/admin/products/{product.pk}/images/{image.pk}/",
        {"source_type": "generated", "image_type": "illustration"},
        format="json",
    )
    assert res.status_code == 200, res.content
    image.refresh_from_db()
    assert (image.source_type, image.image_type) == ("generated", "illustration")

    public = admin_client.get(f"/api/products/{product.slug}/").json()
    assert public["images"][0]["image_type"] == "illustration"


def test_unknown_source_type_is_rejected(admin_client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    product, _ = create_product()
    res = admin_client.post(
        f"/api/admin/products/{product.pk}/images/", {"image": _png(), "source_type": "google"}, format="multipart"
    )
    assert res.status_code == 400
    assert not ProductImage.objects.filter(product=product).exists()
