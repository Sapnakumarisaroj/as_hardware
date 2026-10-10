"""Catalogue import/export: validation rules, all-or-nothing, stock through movements, round trip."""

import io
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.catalog import importer
from apps.catalog.importer import import_file, read_table, run_import
from apps.catalog.importer_export import export_rows, template, write_csv, write_xlsx
from apps.catalog.models import Brand, Product, ProductRelation, ProductVariant
from apps.catalog.taxonomy import apply_taxonomy
from apps.core.testing import create_product, create_store
from apps.inventory.models import Inventory, StockMovement

pytestmark = pytest.mark.django_db

HEADER = (
    "product_sku,product_name,category,subcategory,brand,unit,gst_rate,hsn_code,specifications,is_published,"
    "variant_sku,variant_name,attributes,mrp,price,cost_price,bulk_tiers,stock"
)


@pytest.fixture(autouse=True)
def taxonomy():
    apply_taxonomy()


@pytest.fixture
def store():
    return create_store(code="BLR-01")


def csv_file(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


DRILL = (
    "DR-500,Impact Drill 500W,Power Tools & Accessories,Drills,Bosch,piece,18,8467,Power=500 [W]; Chuck=13 mm,yes,"
    "DR-500-STD,Standard,,3200,2799,2100,10:2700; 25:2650,BLR-01:12"
)
DRILL_KIT = "DR-500,,,,,,,,,,DR-500-KIT,With bits,,3800,3299,,,BLR-01:4"


def run(content: bytes, *, commit=False, name="catalogue.csv", **options):
    return import_file(content, name, dry_run=not commit, **options)


def errors(report) -> list[tuple]:
    return [(e["row"], e["column"]) for e in report.errors]


# --- Happy path ------------------------------------------------------------------------------------


def test_dry_run_reports_everything_and_saves_nothing(store):
    report = run(csv_file(DRILL, DRILL_KIT))
    assert report.ok, report.errors
    assert report.dry_run and not report.committed
    assert [r["action"] for r in report.rows] == ["create", "create"]
    assert report.counts["products_created"] == 1 and report.counts["variants_created"] == 2
    assert report.counts["stock_movements"] == 2
    assert not Product.all_objects.filter(sku="DR-500").exists()
    assert not Brand.objects.filter(name="Bosch").exists()
    assert not StockMovement.objects.exists()


def test_commit_creates_products_variants_tiers_specs_and_stock(store, admin_user):
    report = run(csv_file(DRILL, DRILL_KIT), commit=True, actor=admin_user)
    assert report.committed, report.errors
    product = Product.objects.get(sku="DR-500")
    assert product.category.slug == "power-tools" and product.subcategory.slug == "drills"
    assert product.brand.name == "Bosch" and not product.brand.is_demo and not product.is_demo
    assert product.gst_rate == Decimal("18.00") and product.hsn_code == "8467" and product.is_published
    assert [(s.name, s.value, s.unit) for s in product.specifications.all()] == [
        ("Power", "500", "W"),
        ("Chuck", "13 mm", ""),
    ]
    standard = ProductVariant.objects.get(sku="DR-500-STD")
    assert (standard.mrp, standard.price, standard.cost_price) == (Decimal("3200"), Decimal("2799"), Decimal("2100"))
    assert [(t.min_quantity, t.unit_price) for t in standard.price_tiers.all()] == [
        (10, Decimal("2700")),
        (25, Decimal("2650")),
    ]
    assert Inventory.objects.get(store=store, variant=standard).available_quantity == 12
    movement = StockMovement.objects.get(inventory__variant=standard)
    assert movement.movement_type == StockMovement.Type.ADJUSTMENT and movement.quantity == 12
    assert movement.reason == importer.STOCK_REASON and movement.created_by == admin_user


def test_reimport_is_unchanged_and_stock_differences_are_adjusted(store):
    run(csv_file(DRILL, DRILL_KIT), commit=True)
    again = run(csv_file(DRILL, DRILL_KIT), commit=True)
    assert [r["action"] for r in again.rows] == ["unchanged", "unchanged"]
    assert again.counts["stock_movements"] == 0

    lower = DRILL.replace("BLR-01:12", "BLR-01:7").replace(",2799,", ",2750,")
    report = run(csv_file(lower, DRILL_KIT), commit=True)
    assert [r["action"] for r in report.rows] == ["update", "unchanged"]
    inventory = Inventory.objects.get(store=store, variant__sku="DR-500-STD")
    assert inventory.available_quantity == 7
    assert list(inventory.movements.order_by("id").values_list("quantity", flat=True)) == [12, -5]
    assert ProductVariant.objects.get(sku="DR-500-STD").price == Decimal("2750")


def test_columns_not_in_the_file_are_left_alone(store):
    run(csv_file(DRILL, DRILL_KIT), commit=True)
    report = run(csv_file("DR-500,DR-500-STD,2999", header="product_sku,variant_sku,price"), commit=True)
    assert report.committed, report.errors
    variant = ProductVariant.objects.get(sku="DR-500-STD")
    assert variant.price == Decimal("2999") and variant.cost_price == Decimal("2100")
    assert variant.product.specifications.count() == 2
    assert Inventory.objects.get(store=store, variant=variant).available_quantity == 12


def test_xlsx_import_and_sheet_choice(store):
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "Notes"
    sheet = workbook.create_sheet("Products")
    sheet.append(HEADER.split(","))
    sheet.append(next(iter([DRILL.split(",")])))
    buffer = io.BytesIO()
    workbook.save(buffer)
    report = run(buffer.getvalue(), name="catalogue.xlsx", sheet="Products")
    assert report.ok, report.errors
    with pytest.raises(importer.ImportFileError):
        run(buffer.getvalue(), name="catalogue.xlsx", sheet="Missing")


# --- Validation rules --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "column"),
    [
        (("Power Tools & Accessories", "Plumbing"), "category"),
        (("Drills", "Hammers"), "subcategory"),  # an approved subcategory, but of another department
        ((",18,", ",41,"), "gst_rate"),
        ((",18,", ",-1,"), "gst_rate"),
        ((",3200,2799,", ",2700,2799,"), "price"),  # price above MRP
        (("10:2700; 25:2650", "25:2650; 10:2700"), "bulk_tiers"),  # not ascending
        (("10:2700; 25:2650", "10:2700; 25:2700"), "bulk_tiers"),  # not cheaper
        (("10:2700; 25:2650", "10:2800"), "bulk_tiers"),  # above the price
        (("BLR-01:12", "XXX-99:12"), "stock"),  # unknown store
        (("BLR-01:12", "BLR-01:-3"), "stock"),
        ((",8467,", ",84a7,"), "hsn_code"),
        ((",piece,", ",crate,"), "unit"),
        ((",yes,", ",maybe,"), "is_published"),
        (("Power=500 [W]; Chuck=13 mm", "Power"), "specifications"),
        ((",2100,", ",abc,"), "cost_price"),
    ],
)
def test_each_rule_is_reported_on_its_row_and_column(store, change, column):
    report = run(csv_file(DRILL.replace(*change)))
    assert (2, column) in errors(report), report.errors
    assert not Product.all_objects.filter(sku="DR-500").exists()


def test_new_products_need_name_category_gst_and_prices(store):
    report = run(csv_file("NEW-1,NEW-1-A", header="product_sku,variant_sku"))
    assert set(errors(report)) >= {(2, "product_name"), (2, "category"), (2, "gst_rate"), (2, "mrp"), (2, "price")}


def test_duplicate_rows_and_sku_clashes(store):
    other, other_variant = create_product(name="Other")
    report = run(csv_file(DRILL, DRILL, DRILL_KIT.replace("DR-500-KIT", other_variant.sku)))
    assert (3, "variant_sku") in errors(report)  # the same variant twice
    assert (4, "variant_sku") in errors(report)  # belongs to another product


def test_conflicting_product_columns_on_variant_rows(store):
    report = run(csv_file(DRILL, DRILL_KIT.replace("DR-500,,,", "DR-500,Other name,,")))
    assert (3, "product_name") in errors(report)


def test_file_level_errors():
    with pytest.raises(importer.ImportFileError) as exc:
        read_table(b"a,b\n1,2\n", "x.csv")
    assert exc.value.detail.code == "unknown_columns"
    with pytest.raises(importer.ImportFileError) as exc:
        read_table(b"product_sku\nA\n", "x.csv")
    assert exc.value.detail.code == "missing_columns"
    with pytest.raises(importer.ImportFileError) as exc:
        read_table(b"x", "x.txt")
    assert exc.value.detail.code == "unsupported_file_type"
    with pytest.raises(importer.ImportFileError) as exc:
        read_table(b"x" * (importer.MAX_FILE_BYTES + 1), "x.csv")
    assert exc.value.detail.code == "file_too_large"
    with pytest.raises(importer.ImportFileError) as exc:
        read_table("product_sku,variant_sku\nÄ,B\n".encode("latin-1"), "x.csv")
    assert exc.value.detail.code == "bad_encoding"


# --- Demo data -------------------------------------------------------------------------------------


def test_demo_rows_are_refused_unless_allowed(store):
    product, variant = create_product(name="Demo drill")
    Product.all_objects.filter(pk=product.pk).update(is_demo=True)
    body = csv_file(f"{product.sku},{variant.sku},850", header="product_sku,variant_sku,price")
    assert (2, "product_sku") in errors(run(body))
    assert run(body, commit=True, allow_demo=True).committed
    demo_store = create_store(code="DEMO-01")
    Store = type(demo_store)
    Store.all_objects.filter(pk=demo_store.pk).update(is_demo=True)
    assert (2, "stock") in errors(run(csv_file(DRILL.replace("BLR-01:12", "DEMO-01:12"))))


# --- All or nothing --------------------------------------------------------------------------------


def test_a_failure_while_saving_rolls_back_everything(store, monkeypatch):
    calls = {"n": 0}
    real = importer._Runner.product

    def failing(self, plan):
        calls["n"] += 1
        if plan.sku == "SECOND":
            raise importer.ServiceError("Simulated failure.")
        return real(self, plan)

    monkeypatch.setattr(importer._Runner, "product", failing)
    second = DRILL.replace("DR-500,", "SECOND,", 1).replace("DR-500-STD", "SECOND-1")
    report = run(csv_file(DRILL, second), commit=True)
    assert not report.committed and report.errors[0]["message"] == "Simulated failure."
    assert calls["n"] == 2
    assert not Product.all_objects.filter(sku="DR-500").exists()
    assert not StockMovement.objects.exists() and not Brand.objects.filter(name="Bosch").exists()


# --- Relations, export, round trip -----------------------------------------------------------------


def test_related_skus_link_products_in_the_file_and_in_the_shop(store):
    existing, _ = create_product(name="Drill bit set")
    header = HEADER + ",related_accessory"
    rows = [
        DRILL + f",{existing.sku}",
        DRILL_KIT + ",",
        "BIT-1,Bit,power-tools,drill-bits,,,18,,,no,BIT-1-A,,,100,90,,,,DR-500",
    ]
    report = run(csv_file(*rows, header=header), commit=True)
    assert report.committed, report.errors
    drill = Product.objects.get(sku="DR-500")
    assert list(drill.relations.values_list("related__sku", "kind")) == [(existing.sku, "accessory")]
    assert ProductRelation.objects.filter(product__sku="BIT-1", related=drill).exists()
    assert (2, "related_accessory") in errors(run(csv_file(DRILL + ",NOPE", header=header)))


def test_export_round_trips_through_csv_and_xlsx(store):
    header = HEADER + ",tags,related_alternative,option:Colour"
    rows = [
        DRILL + ',"drill, impact",,Blue',
        DRILL_KIT + ",,,Green",
        "=CMD-1,=Risky name,power-tools,,,,18,,,no,=CMD-1-A,,,100,90,,,,",
    ]
    assert run(csv_file(*rows, header=header), commit=True).committed
    exported = export_rows()
    assert {r["variant_sku"] for r in exported} == {"DR-500-STD", "DR-500-KIT", "=CMD-1-A"}
    csv_bytes = write_csv(exported)
    assert b"'=Risky name" in csv_bytes  # formula injection guard
    for content, name in ((csv_bytes, "export.csv"), (write_xlsx(exported), "export.xlsx")):
        report = run(content, name=name, commit=True)
        assert report.committed, report.errors
        assert {r["action"] for r in report.rows} == {"unchanged"}, report.rows
    assert Product.objects.get(sku="=CMD-1").name == "=Risky name"
    assert ProductVariant.objects.get(sku="DR-500-KIT").attributes == {"Colour": "Green"}


def test_export_leaves_out_demo_rows_and_template_has_the_header(store):
    product, _ = create_product(name="Demo")
    Product.all_objects.filter(pk=product.pk).update(is_demo=True)
    assert product.sku not in {r["product_sku"] for r in export_rows()}
    assert product.sku in {r["product_sku"] for r in export_rows(include_demo=True)}
    blank = read_table(template("csv"), "t.csv")
    assert blank.columns == importer.COLUMN_NAMES and blank.rows == []
    assert read_table(template("xlsx"), "t.xlsx").columns == importer.COLUMN_NAMES


# --- Management commands ---------------------------------------------------------------------------


def test_import_and_export_commands(store, tmp_path):
    path = tmp_path / "catalogue.csv"
    path.write_bytes(csv_file(DRILL, DRILL_KIT))
    out = io.StringIO()
    call_command("import_catalog", str(path), stdout=out)
    assert "Dry run" in out.getvalue() and not Product.all_objects.filter(sku="DR-500").exists()
    call_command("import_catalog", str(path), "--commit", stdout=io.StringIO())
    assert Product.objects.filter(sku="DR-500").exists()

    target = tmp_path / "export.xlsx"
    call_command("export_catalog", "--output", str(target), stdout=io.StringIO())
    assert read_table(target.read_bytes(), "export.xlsx").rows

    bad = tmp_path / "bad.csv"
    bad.write_bytes(csv_file(DRILL.replace(",18,", ",99,")))
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("import_catalog", str(bad), "--commit", stdout=io.StringIO())


def test_run_import_with_an_empty_table_is_an_error():
    report = run_import(importer.Table(columns=["product_sku", "variant_sku"], rows=[]))
    assert not report.ok


def test_moving_a_product_to_another_category_needs_its_subcategory(store):
    run(csv_file(DRILL), commit=True)
    header = "product_sku,variant_sku,category"
    assert (2, "category") in errors(run(csv_file("DR-500,DR-500-STD,safety", header=header)))
    moved = run(csv_file("DR-500,DR-500-STD,safety,gloves", header=header + ",subcategory"), commit=True)
    assert moved.committed, moved.errors
    assert Product.objects.get(sku="DR-500").subcategory.slug == "gloves"
