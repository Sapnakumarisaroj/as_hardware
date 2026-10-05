"""Storefront sitemap (Phase 16): every page a search engine may index, built from the database.

`GET /api/seo/sitemap.xml` lists the home page, published products (/p/<slug>), active categories
(/c/<slug>), brands with visible products (/brand/<slug>) and /brands, with absolute URLs on
`FRONTEND_URL`. The web server can serve it as /sitemap.xml (DEPLOYMENT.md). One file holds up to
50,000 URLs (the sitemap limit); a larger catalogue would split it with a sitemap index.
"""

from xml.sax.saxutils import escape

from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponse
from django.views.decorators.cache import cache_page

from .models import Brand, Category, Product

MAX_URLS = 50_000


def sitemap_entries() -> list[tuple[str, str | None]]:
    """(path, last modified ISO date or None), home first."""
    entries: list[tuple[str, str | None]] = [("/", None), ("/brands", None)]
    entries += [
        (f"/c/{slug}", None)
        for slug in Category.objects.filter(is_active=True).order_by("pk").values_list("slug", flat=True)
    ]
    visible = Q(products__is_active=True, products__is_published=True, products__is_deleted=False)
    brands = Brand.objects.filter(is_active=True).annotate(n=Count("products", filter=visible)).filter(n__gt=0)
    entries += [(f"/brand/{slug}", None) for slug in brands.order_by("pk").values_list("slug", flat=True)]
    products = (
        Product.objects.filter(is_active=True, is_published=True).order_by("pk").values_list("slug", "updated_at")
    )
    entries += [(f"/p/{slug}", updated.date().isoformat()) for slug, updated in products]
    return entries[:MAX_URLS]


@cache_page(60 * 60)
def sitemap_view(request):
    base = settings.FRONTEND_URL
    rows = []
    for path, modified in sitemap_entries():
        lastmod = f"<lastmod>{modified}</lastmod>" if modified else ""
        rows.append(f"<url><loc>{escape(base + path)}</loc>{lastmod}</url>")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(rows) + "</urlset>\n"
    )
    return HttpResponse(body, content_type="application/xml")
