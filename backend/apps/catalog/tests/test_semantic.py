"""Semantic search (Phase 13): related words, typos, Hindi/Hinglish, the embedding index, the hybrid
ranking, the keyword fallback, and the administrator tools."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.catalog import selectors
from apps.catalog.models import Product, ProductEmbedding
from apps.catalog.search import KeywordSearchBackend, get_search_backend
from apps.catalog.semantic import benchmark, index
from apps.catalog.semantic.backend import HybridSearchBackend
from apps.catalog.semantic.embedders import HashingEmbedder, get_embedder
from apps.catalog.semantic.expand import expand
from apps.core.models import Job
from apps.core.testing import create_category, create_product, create_store

pytestmark = pytest.mark.django_db

HYBRID = "apps.catalog.semantic.backend.HybridSearchBackend"


@pytest.fixture(autouse=True)
def semantic_on(settings):
    settings.SEMANTIC_EMBEDDER = "hashing"
    settings.CATALOG_SEARCH_BACKEND = HYBRID
    get_search_backend.cache_clear()
    index.reset_caches()
    yield
    get_search_backend.cache_clear()
    index.reset_caches()


@pytest.fixture
def shop():
    store = create_store()
    tools = create_category("Tools")
    drills = create_category("Drills", parent=tools)
    hammers = create_category("Hammers", parent=tools)
    plumbing = create_category("Plumbing")
    sealants = create_category("Sealants", parent=plumbing)
    electrical = create_category("Electrical")
    wires = create_category("Wires", parent=electrical)
    made = {}
    for key, name, price, category, sub, tags, stock in [
        ("drill", "Corded Impact Drill 650W", "3200.00", tools, drills, ["drill", "impact", "concrete"], 5),
        ("bits", "Masonry Drill Bit Set", "329.00", tools, drills, ["drill bit", "masonry"], 20),
        ("hammer", "Claw Hammer", "450.00", tools, hammers, ["hammer"], 8),
        ("sealant", "Silicone Sealant Clear", "210.00", plumbing, sealants, ["silicone", "sealant", "waterproof"], 30),
        ("ptfe", "PTFE Thread Seal Tape", "60.00", plumbing, sealants, ["teflon", "ptfe", "leak"], 0),
        ("wire", "Copper Wire 90 m", "1749.00", electrical, wires, ["wire", "house wiring", "copper"], 12),
    ]:
        made[key], _ = create_product(
            name=name, price=price, mrp=price, category=category, subcategory=sub, tags=tags, stock=stock, store=store
        )
    index.sync_products()
    return made


def _search(client, q, **extra):
    response = client.get("/api/products/", {"q": q, **extra})
    assert response.status_code == 200
    return response.json()


def _names(payload):
    return [p["name"] for p in payload["results"]]


# --- Meaning, synonyms, languages, typos -------------------------------------------------------------


def test_description_finds_products_keyword_search_cannot(api_client, shop, settings):
    query = "machine for drilling"
    settings.CATALOG_SEARCH_BACKEND = "apps.catalog.search.KeywordSearchBackend"
    get_search_backend.cache_clear()
    assert "Corded Impact Drill 650W" not in _names(_search(api_client, "thing to bore into a wall"))
    settings.CATALOG_SEARCH_BACKEND = HYBRID
    get_search_backend.cache_clear()
    payload = _search(api_client, query)
    assert "Corded Impact Drill 650W" in _names(payload)[:3]
    assert payload["search"]["mode"] == "hybrid"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("machine for drilling concrete", "Corded Impact Drill 650W"),
        ("water leakage fixing material", "Silicone Sealant Clear"),
        ("wire for AC", "Copper Wire 90 m"),
        ("Mujhe diwar me hole karne ka saman chahiye", "Corded Impact Drill 650W"),
        ("दीवार में छेद करने की मशीन", "Corded Impact Drill 650W"),
        ("bijli ka tar", "Copper Wire 90 m"),
        ("diwar me kil thokna", "Claw Hammer"),
    ],
)
def test_natural_language_hindi_and_hinglish_queries(api_client, shop, query, expected):
    assert expected in _names(_search(api_client, query))[:3]


@pytest.mark.parametrize(
    ("typo", "expected"), [("hamer", "Claw Hammer"), ("silicon sealent", "Silicone Sealant Clear")]
)
def test_typos_are_corrected_against_catalogue_words(api_client, shop, typo, expected):
    payload = _search(api_client, typo)
    assert _names(payload)[0] == expected


def test_results_explain_why_when_the_match_is_not_obvious(api_client, shop):
    payload = _search(api_client, "machine for drilling concrete")
    drill = next(p for p in payload["results"] if p["name"] == "Corded Impact Drill 650W")
    assert drill["match_type"] in {"keyword", "related", "semantic"}
    assert drill["match_reason"]
    typo = _search(api_client, "hamer")["results"][0]
    assert typo["match_type"] == "related" and typo["match_reason"] == "Showing “hammer” for “hamer”"


def test_short_words_inside_other_words_are_not_matches(api_client, shop):
    """Keyword search matches "ac" inside "Hacksaw" and "tap" inside "Tape"; the hybrid ranking does not."""
    tools = shop["hammer"].category
    create_product(name="Hacksaw Frame", price="250.00", category=tools, tags=["saw"], stock=3)
    create_product(name="Measuring Tape 5 m", price="150.00", category=tools, tags=["measure"], stock=3)
    index.sync_products()
    names = _names(_search(api_client, "wire for AC"))
    assert names[0] == "Copper Wire 90 m" and "Hacksaw Frame" not in names
    assert "Measuring Tape 5 m" not in _names(_search(api_client, "water leakage fixing material"))
    # … while the plain keyword search still finds them (unchanged Phase 4 behaviour)
    plain = KeywordSearchBackend().search(selectors.product_queryset(), "wire for AC")
    assert "Hacksaw Frame" in [p.name for p in plain.queryset]


def test_a_query_whose_only_matches_are_accidental_returns_an_empty_page(api_client, shop):
    # "me" is inside "Hammer" and nothing else matches: no results, and no error from the relevance ordering
    payload = _search(api_client, "me qqqqzz")
    assert "Claw Hammer" not in _names(payload)
    assert _search(api_client, "me qqqqzz", ordering="price")["count"] == payload["count"]


def test_exact_names_still_rank_first(api_client, shop):
    assert _names(_search(api_client, "claw hammer"))[0] == "Claw Hammer"
    assert _names(_search(api_client, "masonry drill bit"))[0] == "Masonry Drill Bit Set"


# --- Real products only ------------------------------------------------------------------------------


def test_only_real_published_products_with_database_prices(api_client, shop):
    hidden, _ = create_product(name="Secret Drill Machine", price="10.00", category=shop["drill"].category, stock=5)
    hidden.is_published = False
    hidden.save()
    index.sync_products()
    payload = _search(api_client, "machine for drilling concrete")
    assert "Secret Drill Machine" not in _names(payload)
    real = {p.name: p for p in selectors.product_queryset()}
    for item in payload["results"]:
        assert item["name"] in real, "a result that is not in the database"
        assert Decimal(item["price"]) == real[item["name"]].price


def test_a_query_with_no_meaning_returns_nothing_not_inventions(api_client, shop):
    assert _search(api_client, "qwertyuiop zxcvb")["results"] == []


def test_filters_sorting_and_pagination_still_apply(api_client, shop):
    assert _names(_search(api_client, "machine for drilling", in_stock="true", max_price="1000")) == [
        "Masonry Drill Bit Set"
    ]
    prices = {p.name: p.price for p in selectors.product_queryset()}
    cheap_first = _names(_search(api_client, "machine for drilling concrete", ordering="price"))
    assert cheap_first == sorted(cheap_first, key=lambda n: prices[n])
    page = _search(api_client, "tool for leaks and drilling", page_size=1)
    assert len(page["results"]) == 1 and page["count"] >= 2


def test_suggestions_use_the_same_search(api_client, shop):
    response = api_client.get("/api/search/suggest/", {"q": "hamer"})
    assert response.status_code == 200
    assert response.json()["products"][0]["name"] == "Claw Hammer"


# --- Fallback ----------------------------------------------------------------------------------------


def test_keyword_search_when_semantic_is_off(api_client, shop, settings):
    settings.SEMANTIC_EMBEDDER = "none"
    payload = _search(api_client, "hammer")
    assert _names(payload) == ["Claw Hammer"]
    assert index.similarities("hammer") == {}


def test_a_failing_model_falls_back_to_keyword_results(api_client, shop, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(index, "similarities", boom)
    payload = _search(api_client, "hammer")
    assert _names(payload) == ["Claw Hammer"]
    assert "mode" not in payload["search"]


def test_missing_model_means_keyword_plus_related_words(api_client, shop, settings):
    settings.SEMANTIC_EMBEDDER = "sentence_transformers"
    settings.SEMANTIC_MODEL = "does-not-exist/none"
    settings.SEMANTIC_MODEL_LOCAL_ONLY = True
    assert get_embedder().available is False
    assert "Corded Impact Drill 650W" in _names(_search(api_client, "machine for drilling concrete"))
    assert index.status()["ready"] is False
    with pytest.raises(RuntimeError):
        index.sync_products()


def test_searches_while_the_model_is_loading_use_keywords(api_client, shop, settings):
    settings.SEMANTIC_EMBEDDER = "sentence_transformers"
    settings.SEMANTIC_MODEL = "does-not-exist/loading"
    embedder = get_embedder()
    embedder._lock.acquire()  # the warm-up thread is busy loading it
    try:
        assert embedder.available is False
        assert _names(_search(api_client, "hammer")) == ["Claw Hammer"]
    finally:
        embedder._lock.release()


def test_search_without_an_index_still_works(api_client, shop):
    ProductEmbedding.objects.all().delete()
    index.reset_caches()
    assert "Corded Impact Drill 650W" in _names(_search(api_client, "machine for drilling concrete"))
    assert _names(_search(api_client, "hammer")) == ["Claw Hammer"]


# --- The index ---------------------------------------------------------------------------------------


def test_index_embeds_once_and_only_refreshes_changed_products(shop):
    assert ProductEmbedding.objects.count() == Product.objects.count()
    assert index.sync_products().unchanged == Product.objects.count()
    hammer = shop["hammer"]
    hammer.tags = ["hammer", "mallet"]
    hammer.save()
    assert index.status()["stale"] == 1
    result = index.sync_products()
    assert (result.embedded, result.unchanged) == (1, Product.objects.count() - 1)
    assert index.status()["stale"] == 0
    assert index.sync_products(force=True).embedded == Product.objects.count()


def test_unchanged_products_are_not_embedded_again(shop, monkeypatch):
    calls = []
    original = HashingEmbedder.embed
    monkeypatch.setattr(HashingEmbedder, "embed", lambda self, texts: calls.append(len(texts)) or original(self, texts))
    index.sync_products()
    assert calls == []


def test_query_vectors_are_cached(api_client, shop, monkeypatch):
    calls = []
    original = HashingEmbedder.embed
    monkeypatch.setattr(HashingEmbedder, "embed", lambda self, texts: calls.append(texts) or original(self, texts))
    _search(api_client, "machine for drilling concrete")
    _search(api_client, "machine for drilling concrete")
    assert len(calls) == 1


def test_soft_deleted_products_leave_the_index(shop):
    shop["hammer"].delete()
    assert index.sync_products().removed == 1
    assert not ProductEmbedding.objects.filter(product_id=shop["hammer"].pk).exists()


def test_switching_embedder_marks_old_vectors_and_rebuilds(shop, settings):
    settings.SEMANTIC_EMBEDDER = "sentence_transformers"
    settings.SEMANTIC_MODEL = "does-not-exist/none"
    settings.SEMANTIC_MODEL_LOCAL_ONLY = True
    status = index.status()
    assert status["other_embedder"] == Product.objects.count() and status["indexed"] == 0


def test_saving_a_product_queues_a_refresh_that_updates_its_vector(shop, django_capture_on_commit_callbacks):
    hammer = shop["hammer"]
    before = ProductEmbedding.objects.get(product=hammer).text_hash
    with django_capture_on_commit_callbacks(execute=True):
        hammer.tags = ["hammer", "mallet", "sledge"]
        hammer.save()
    assert Job.objects.filter(name="catalog.sync_embedding").exists()
    assert ProductEmbedding.objects.get(product=hammer).text_hash != before


def test_no_jobs_are_queued_while_semantic_search_is_off(settings):
    settings.SEMANTIC_EMBEDDER = "none"
    create_product(name="Plain Hammer", price="10.00", category=create_category("X"), stock=1)
    assert not Job.objects.filter(name__startswith="catalog.").exists()


def test_management_commands(shop, capsys):
    ProductEmbedding.objects.all().delete()
    call_command("rebuild_search_index")
    assert ProductEmbedding.objects.count() == Product.objects.count()
    call_command("rebuild_search_index", "--status")
    call_command("benchmark_search")
    assert "hybrid" in capsys.readouterr().out


# --- Expansion and ranking units --------------------------------------------------------------------------


def test_expand_maps_descriptions_hinglish_and_devanagari_to_catalogue_words():
    assert "drill" in expand("machine for drilling concrete").terms
    assert "ptfe tape" in expand("water leakage fixing material").terms
    assert "tap" in expand("nal tapak raha hai").terms
    assert "drill" in expand("दीवार में छेद करने की मशीन").terms
    assert expand("qwertyuiop").terms == []


def test_expand_corrects_typos_only_against_catalogue_words():
    found = expand("hamer for the wall", vocabulary=frozenset({"hammer", "wall"}))
    assert found.typos == {"hamer": "hammer"} and "hammer" in found.terms
    assert expand("hamer", vocabulary=frozenset({"drill"})).typos == {}
    assert expand("cover for head", vocabulary=frozenset({"thread", "cover"})).typos == {}  # a word, not a typo


@pytest.mark.parametrize(
    ("query", "term"),
    [
        ("kabza chahiye", "hinge"), ("कब्जे", "hinge"), ("18 mm plai", "plywood"), ("pench", "screws"),
        ("daraz channel", "drawer channel"), ("almari ka handal", "handle"), ("chitkani", "tower bolt"),
        ("tala chabi", "lock"), ("barma", "drill"), ("hathoda", "hammer"), ("dastane", "gloves"),
        ("kaanch ka darwaza", "glass door"), ("sunmica", "laminate"), ("kil", "nails"),
    ],
)  # fmt: skip
def test_expand_knows_the_shops_department_words(query, term):
    assert term in expand(query).terms


def test_department_words_find_products_and_the_benchmark_has_them(api_client, shop):
    hinges = create_category("Hinges, Channels & Handles")
    store = create_store(name="Second")
    create_product(
        name="Soft-Close Concealed Hinge (Pair)", category=hinges, tags=["hinge", "kabja"], stock=5, store=store
    )
    create_product(
        name="Telescopic Drawer Channel (Pair)", category=hinges, tags=["drawer channel"], stock=5, store=store
    )
    index.sync_products()
    assert "Soft-Close Concealed Hinge (Pair)" in _names(_search(api_client, "kabza chahiye"))[:3]
    assert "Telescopic Drawer Channel (Pair)" in _names(_search(api_client, "daraz"))[:3]
    queries = [q for q, _ in benchmark.QUERIES]
    assert {"kabza chahiye", "18 mm plai", "pench", "chitkani", "daraz channel"} <= set(queries)


def test_hybrid_keeps_keyword_hits_and_adds_related_ones(shop):
    base = selectors.product_queryset()
    keyword = KeywordSearchBackend().search(base, "drill")
    hybrid = HybridSearchBackend().search(base, "drill")
    assert set(keyword.queryset.values_list("pk", flat=True)) <= set(hybrid.queryset.values_list("pk", flat=True))


def test_benchmark_reports_all_three_modes(shop):
    report = benchmark.run([("hamer", ["Claw Hammer"]), ("qwerty", ["Nothing"])])
    assert report["hybrid"]["found"] == 1 and report["keyword"]["found"] == 0 and report["related"]["found"] == 1


# --- Administrator tools ---------------------------------------------------------------------------------


def test_index_status_rebuild_and_explain_for_administrators(admin_client, shop):
    status = admin_client.get("/api/admin/search/index/").json()
    assert status["ready"] is True and status["indexed"] == status["products"] == Product.objects.count()
    assert status["search_backend"] == "hybrid" and status["embedder"]["kind"] == "hashing"

    ProductEmbedding.objects.filter(product=shop["hammer"]).delete()
    assert admin_client.get("/api/admin/search/index/").json()["missing"] == 1
    rebuilt = admin_client.post("/api/admin/search/index/rebuild/", {}, format="json").json()
    assert rebuilt["result"]["embedded"] == 1 and rebuilt["status"]["missing"] == 0
    assert (
        admin_client.post("/api/admin/search/index/rebuild/", {"force": True}, format="json").json()["result"][
            "embedded"
        ]
        == Product.objects.count()
    )
    assert admin_client.post(f"/api/admin/search/index/products/{shop['hammer'].pk}/").status_code == 200
    assert admin_client.post("/api/admin/search/index/products/999999/").status_code == 404

    explained = admin_client.get("/api/admin/search/explain/", {"q": "machine for drilling concrete"}).json()
    assert explained["mode"] == "hybrid" and explained["related_terms"]
    top = explained["results"][0]
    assert {"keyword", "related", "semantic", "final", "name"} <= set(top)
    assert admin_client.get("/api/admin/search/explain/").status_code == 400


def test_rebuild_reports_unavailable_semantic_search(admin_client, shop, settings):
    settings.SEMANTIC_EMBEDDER = "none"
    response = admin_client.post("/api/admin/search/index/rebuild/", {}, format="json")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "semantic_unavailable"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/search/index/"),
        ("post", "/api/admin/search/index/rebuild/"),
        ("post", "/api/admin/search/index/products/1/"),
        ("get", "/api/admin/search/explain/?q=drill"),
    ],
)
def test_only_administrators_may_use_the_index_tools(api_client, auth_client, staff_client, shop, method, path):
    assert getattr(api_client, method)(path).status_code == 401
    assert getattr(auth_client, method)(path).status_code == 403  # a customer
    assert getattr(staff_client, method)(path).status_code == 403  # a store manager
