"""Final catalogue import package for a fresh (production) database, from the reviewed staging sheets.

    python -I catalogue/build_release.py                      # writes catalogue/release/ (git-ignored)
    python3 -I catalogue/build_release.py --verify EXPORT.csv # compare a database export with the package
                                                              # (needs only catalogue/release/, no private sheets)

Sources, applied in this order (later sheets win, each only for the columns it has):
  staging/full_catalogue_products.csv, staging/fevicol_pilot_products.csv   products, variants, descriptions
  staging/full_catalogue_pilot_prices.csv                                   reference prices (not approved)
  staging/full_catalogue_approved_prices.csv                                owner decision 11-Oct-2026 (95% rule)
  staging/owner_review_prices.csv                       PRIVATE, not in Git  owner's review of the 128 waiting options
  staging/gst_hsn.csv                                                       GST rate + HSN per product
  staging/full_catalogue_publish.csv, staging/owner_review_publish.csv*     what is published (*private)
  staging/initial_stock_blr01.csv                                           configured stock at BLR-01
  staging/full_catalogue_images.csv, staging/fevicol_pilot_images.csv       pictures under assets/as-hardware-images
Picture rights: the owner approved the folder pictures on 11-Oct-2026 (catalogue/README.md); the image sheets
still say "unverified", so the package records that decision explicitly (PICTURE_RIGHTS below).

Nothing is guessed. The build stops (exit 1, nothing written) when a price is missing, not approved, above its MRP,
or set to different values by two approval sheets; when stock, a publish row, a GST row or a picture points at an
unknown SKU or a missing file; or when a published product has no approved option or no picture.

Writes catalogue/release/ (contains the private prices: keep it out of Git, copy it to the server privately):
  01_products.csv   products + variants: final MRP/price (approved), GST/HSN, stock; imported unpublished
  02_images.csv     pictures with the owner's rights decision
  03_publish.csv    the products to publish (after their pictures are attached)
  shop_setup.json   store BLR-01, its delivery zone and the delivery charges (from the local database, optional)
  REPORT.md         counts and the items that still need the owner (never imported as uncertain data)
  SHA256SUMS        checksums of the files above
"""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STAGING, RELEASE = HERE / "staging", HERE / "release"
IMAGE_ROOT = REPO / "assets" / "as-hardware-images"
# Unix line endings on every OS: the server checks the package with `sha256sum -c SHA256SUMS`.
TEXT = {"encoding": "utf-8", "newline": "\n"}
STORE = "BLR-01"
PICTURE_RIGHTS = {
    "source_type": "owner_approved",
    "licence": "From assets/as-hardware-images (came with the HomeRun data export). Approved for use by the shop "
    "owner on 11-Oct-2026; rights not independently verified.",
}

PRODUCT_SHEETS = ("full_catalogue_products.csv", "fevicol_pilot_products.csv")
PRICE_SHEETS = (  # (file, private?)
    ("full_catalogue_pilot_prices.csv", False),
    ("full_catalogue_approved_prices.csv", False),
    ("owner_review_prices.csv", True),
)
PUBLISH_SHEETS = (("full_catalogue_publish.csv", False), ("owner_review_publish.csv", True))
IMAGE_SHEETS = ("full_catalogue_images.csv", "fevicol_pilot_images.csv")
PRODUCT_COLUMNS = ("product_name", "category", "subcategory", "brand", "unit", "gst_rate", "hsn_code",
                   "short_description", "description", "highlights", "uses", "specifications", "tags")  # fmt: skip
VARIANT_COLUMNS = (
    "variant_sku",
    "variant_name",
    "attributes",
    "mrp",
    "price",
    "price_approved",
    "price_source",
    "stock",
)


class Problems(list):
    def add(self, where: str, message: str) -> None:
        self.append(f"{where}: {message}")


def read(name: str) -> list[dict]:
    path = STAGING / name
    if not path.is_file():
        raise SystemExit(f"Missing {path.relative_to(REPO)}. Private sheets are not in Git: copy them from the owner.")
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def money(value: str) -> Decimal | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return Decimal("NaN")
    return amount


def build(problems: Problems) -> dict:
    products: dict[str, dict] = {}
    variants: dict[str, dict] = {}
    for sheet in PRODUCT_SHEETS:
        for row in read(sheet):
            psku, vsku = row["product_sku"].strip(), row["variant_sku"].strip()
            product = products.setdefault(psku, {"product_sku": psku, "variants": []})
            for column in PRODUCT_COLUMNS:
                value = (row.get(column) or "").strip()
                if value and product.get(column) and product[column] != value:
                    problems.add(f"{sheet} {vsku}", f"{column} differs between rows of {psku}")
                if value:
                    product[column] = value
            if vsku in variants:
                problems.add(f"{sheet} {vsku}", "variant listed twice")
                continue
            variants[vsku] = {"product_sku": psku, "variant_sku": vsku, "variant_name": row.get("variant_name", ""),
                              "attributes": row.get("attributes", ""), "mrp": money(row.get("mrp")),
                              "price": money(row.get("price")), "price_approved": "no", "price_source": "",
                              "approved_by": None, "stock": ""}  # fmt: skip
            product["variants"].append(vsku)

    # Prices: a reference ("no") row may be superseded by an approval; two approvals must agree.
    for sheet, _private in PRICE_SHEETS:
        for row in read(sheet):
            vsku = row["variant_sku"].strip()
            variant = variants.get(vsku)
            if variant is None:
                problems.add(f"{sheet} {vsku}", "price for an unknown variant")
                continue
            if variant["product_sku"] != row["product_sku"].strip():
                problems.add(f"{sheet} {vsku}", "product_sku differs from the product sheet")
            mrp, price = money(row["mrp"]), money(row["price"])
            approved = (row.get("price_approved") or "").strip().lower()
            if approved == "yes":
                if variant["approved_by"] and (variant["mrp"], variant["price"]) != (mrp, price):
                    problems.add(f"{sheet} {vsku}", f"approved price conflicts with {variant['approved_by']}")
                    continue
                variant["approved_by"] = sheet
            elif variant["approved_by"]:
                problems.add(
                    f"{sheet} {vsku}", f"an unapproved price would replace the approval in {variant['approved_by']}"
                )
                continue
            variant.update(mrp=mrp, price=price, price_approved=approved or "no",
                           price_source=(row.get("price_source") or "").strip())  # fmt: skip

    for vsku, v in variants.items():
        where = f"{v['product_sku']} {vsku}"
        if v["price_approved"] != "yes":
            problems.add(where, "no approved price (not imported as uncertain data; list it for the owner)")
        elif v["mrp"] is None or v["price"] is None or v["mrp"].is_nan() or v["price"].is_nan():
            problems.add(where, "approved without a valid MRP and price")
        elif v["price"] <= 0 or v["mrp"] <= 0 or v["price"] > v["mrp"]:
            problems.add(where, "price must be above 0 and not above the MRP")
        elif v["price"].as_tuple().exponent < -2 or v["mrp"].as_tuple().exponent < -2:
            problems.add(where, "more than 2 decimals")

    # GST / HSN
    for row in read("gst_hsn.csv"):
        product = products.get(row["product_sku"].strip())
        if product is None:
            problems.add(f"gst_hsn.csv {row['product_sku']}", "unknown product")
            continue
        product["gst_rate"], product["hsn_code"] = row["gst_rate"].strip(), row["hsn_code"].strip()
        product["gst_reviewed"] = True

    # Stock (only for approved variants; one store)
    for row in read("initial_stock_blr01.csv"):
        vsku, stock = row["variant_sku"].strip(), row["stock"].strip()
        variant = variants.get(vsku)
        if variant is None:
            problems.add(f"initial_stock_blr01.csv {vsku}", "stock for an unknown variant")
        elif not stock.startswith(f"{STORE}:") or not stock.split(":", 1)[1].isdigit():
            problems.add(f"initial_stock_blr01.csv {vsku}", f"stock must look like {STORE}:<quantity>")
        else:
            variant["stock"] = stock

    # Publishing
    published: dict[str, set[str]] = defaultdict(set)
    for sheet, _private in PUBLISH_SHEETS:
        for row in read(sheet):
            psku, vsku = row["product_sku"].strip(), row["variant_sku"].strip()
            if variants.get(vsku, {}).get("product_sku") != psku:
                problems.add(f"{sheet} {vsku}", "publish row for an unknown variant/product")
            elif row["is_published"].strip().lower() == "yes":
                published[psku].add(vsku)

    # Pictures
    images, seen_files = [], {}
    for sheet in IMAGE_SHEETS:
        for row in read(sheet):
            psku, file = row["product_sku"].strip(), row["file"].strip()
            if psku not in products:
                problems.add(f"{sheet} {psku}", "picture for an unknown product")
                continue
            if not (IMAGE_ROOT / file).is_file():
                problems.add(f"{sheet} {psku}", f"missing file {file}")
            if seen_files.setdefault(file, psku) != psku:
                problems.add(f"{sheet} {psku}", f"{file} is also listed for {seen_files[file]}")
            images.append({"product_sku": psku, "file": file, "is_primary": row["is_primary"],
                           "alt_text": row["alt_text"], **PICTURE_RIGHTS})  # fmt: skip
    pictured = {i["product_sku"] for i in images}

    for psku in published:
        if psku not in pictured:
            problems.add(psku, "published without a picture")
        if not any(variants[v]["price_approved"] == "yes" for v in products[psku]["variants"]):
            problems.add(psku, "published without an approved option")
    for psku, product in products.items():
        if not product.get("category") or not product.get("product_name") or not product.get("gst_rate"):
            problems.add(psku, "product needs a name, category and GST rate")
    return {"products": products, "variants": variants, "published": published, "images": images}


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def product_rows(data: dict) -> list[dict]:
    rows = []
    for psku, product in data["products"].items():
        for i, vsku in enumerate(product["variants"]):
            v = data["variants"][vsku]
            shared = {c: product.get(c, "") for c in PRODUCT_COLUMNS} if i == 0 else {}
            rows.append({"product_sku": psku, **shared, **{c: v[c] for c in VARIANT_COLUMNS}})
    return rows


def shop_setup(problems: Problems) -> list | None:
    """Store BLR-01, its delivery zone and the delivery charges, read from the local database (dumpdata only
    reads). Managers and 'updated by' are dropped: they point at local user accounts."""
    backend = REPO / "backend"
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev"}
    result = subprocess.run(
        [sys.executable, "manage.py", "dumpdata", "stores.store", "delivery.deliveryzone", "delivery.deliverycharges"],
        cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
    )  # fmt: skip
    if result.returncode:
        problems.add("shop_setup.json", f"dumpdata failed: {result.stderr.strip()[-300:]}")
        return None
    objects = json.loads(result.stdout)
    for obj in objects:
        obj["fields"].pop("managers", None)
        if "updated_by" in obj["fields"]:
            obj["fields"]["updated_by"] = None
    stores = [o for o in objects if o["model"] == "stores.store"]
    if [s["fields"]["code"] for s in stores] != [STORE]:
        problems.add("shop_setup.json", f"expected exactly one store, {STORE}")
    if any(s["fields"].get("is_demo") for s in stores):
        problems.add("shop_setup.json", "the store is demo data")
    return objects


def report(data: dict, setup: list | None) -> str:
    products, variants, published = data["products"], data["variants"], data["published"]
    unpublished = sorted(p for p in products if p not in published)
    pictured = {i["product_sku"] for i in data["images"]}
    gst_open = sorted(p for p, d in products.items() if not d.get("gst_reviewed"))
    hsn_blank = sorted(p for p in published if not products[p].get("hsn_code"))
    lines = [
        "# Catalogue release report", "",
        f"- Products: {len(products)} ({len(published)} published, {len(unpublished)} unpublished)",
        f"- Options (variants): {len(variants)}, all with an approved MRP and price "
        f"({Counter(v['approved_by'] for v in variants.values()).most_common()})",
        f"- Stock rows: {sum(1 for v in variants.values() if v['stock'])} "
        f"({Counter(v['stock'] for v in variants.values()).most_common(3)})",
        f"- Pictures: {len(data['images'])} for {len(pictured)} products, rights: {PICTURE_RIGHTS['source_type']}",
        f"- Shop setup: {', '.join(sorted({o['model'] for o in setup})) if setup else 'not included'}",
        "", "## Needs the owner (imported exactly as reviewed; nothing here was guessed)", "",
        f"### Unpublished: no picture ({len(unpublished)})",
        *[f"- {p} {products[p].get('product_name', '')}" + ("" if p not in pictured else " (has a picture)")
          for p in unpublished],
        "", f"### GST/HSN not decided: 18% placeholder, HSN blank ({len(gst_open)})",
        *[f"- {p} {products[p].get('product_name', '')} ({'published' if p in published else 'unpublished'})"
          for p in gst_open],
        "", f"### Published with a blank HSN code ({len(hsn_blank)})",
        *[f"- {p} {products[p].get('product_name', '')}" for p in hsn_blank],
    ]  # fmt: skip
    if setup:
        store = next(o["fields"] for o in setup if o["model"] == "stores.store")
        if store.get("latitude") is None or store.get("longitude") is None:
            lines += ["", "### Store BLR-01 has no map coordinates",
                      "Delivery distance (and distance-band charges) need the verified shop location. Set it in the "
                      "dashboard (Stores) after the import."]  # fmt: skip
    return "\n".join(lines) + "\n"


def load_package(release: Path, problems: Problems) -> dict:
    """The package as written (so the server needs only catalogue/release/, not the private staging sheets)."""
    sums = release / "SHA256SUMS"
    if not sums.is_file():
        problems.add(str(release), "no SHA256SUMS: not a release package")
        return {"products": {}, "variants": {}, "published": {}}
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        path = release / name.strip()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.add(name, "checksum mismatch: the package was changed or copied incompletely")
    products: dict[str, dict] = {}
    variants: dict[str, dict] = {}
    with (release / "01_products.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            product = products.setdefault(row["product_sku"], {"variants": []})
            for column in PRODUCT_COLUMNS:
                if row.get(column):
                    product[column] = row[column]
            product["variants"].append(row["variant_sku"])
            variants[row["variant_sku"]] = {**row, "mrp": money(row["mrp"]), "price": money(row["price"])}
    with (release / "03_publish.csv").open(encoding="utf-8", newline="") as f:
        published = {row["product_sku"] for row in csv.DictReader(f) if row["is_published"] == "yes"}
    return {"products": products, "variants": variants, "published": published}


def verify(data: dict, export: Path) -> int:
    """Compare an `export_catalog --output X.csv` of a database with the package (any database engine)."""
    with export.open(encoding="utf-8-sig", newline="") as f:  # export_catalog writes a BOM (for Excel)
        rows = list(csv.DictReader(f))
    got = {r["variant_sku"]: r for r in rows}
    exported_products = {}
    for r in rows:
        if r.get("product_name"):
            exported_products[r["product_sku"]] = r
    diffs = Problems()
    expected = data["variants"]
    for vsku in sorted(set(expected) | set(got)):
        if vsku not in got:
            diffs.add(vsku, "missing in the database")
            continue
        if vsku not in expected:
            diffs.add(vsku, "in the database but not in the package")
            continue
        e, g = expected[vsku], got[vsku]
        for column in ("mrp", "price"):
            if money(g[column]) != e[column]:
                diffs.add(vsku, f"{column} differs")
        if g["price_approved"] != e["price_approved"]:
            diffs.add(vsku, "price_approved differs")
        if g["stock"] != e["stock"]:
            diffs.add(vsku, "stock differs")
        if g["product_sku"] != e["product_sku"]:
            diffs.add(vsku, "belongs to another product")
    for psku, product in data["products"].items():
        g = exported_products.get(psku)
        if g is None:
            diffs.add(psku, "product missing in the database export")
            continue
        if (g["is_published"] == "yes") != (psku in data["published"]):
            diffs.add(psku, "published state differs")
        if money(g["gst_rate"]) != money(product.get("gst_rate")) or g["hsn_code"] != product.get("hsn_code", ""):
            diffs.add(psku, "GST/HSN differs")
        for column in ("product_name", "brand", "unit"):
            if (g.get(column) or "") != product.get(column, ""):
                diffs.add(psku, f"{column} differs")
    for d in diffs[:40]:
        print("DIFF", d)
    print(f"{len(diffs)} difference(s) between {export.name} and the package "
          f"({len(expected)} options, {len(data['products'])} products).")  # fmt: skip
    return 1 if diffs else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", type=Path, help="Compare an export_catalog CSV with the package and exit.")
    parser.add_argument("--release", type=Path, default=RELEASE, help="Package folder for --verify.")
    parser.add_argument("--no-shop-setup", action="store_true", help="Don't export the store/delivery settings.")
    args = parser.parse_args()

    problems = Problems()
    if args.verify:
        data = load_package(args.release, problems)
        for p in problems:
            print("PROBLEM", p)
        return verify(data, args.verify) or (1 if problems else 0)
    data = build(problems)
    setup = None if args.no_shop_setup else shop_setup(problems)
    if problems:
        for p in problems:
            print("PROBLEM", p)
        print(f"{len(problems)} problem(s): nothing written.")
        return 1

    RELEASE.mkdir(exist_ok=True)
    write_csv(RELEASE / "01_products.csv", ["product_sku", *PRODUCT_COLUMNS, *VARIANT_COLUMNS], product_rows(data))
    write_csv(RELEASE / "02_images.csv", ["product_sku", "file", "is_primary", "alt_text", "source_type", "licence"],
              data["images"])  # fmt: skip
    write_csv(RELEASE / "03_publish.csv", ["product_sku", "variant_sku", "is_published"],
              [{"product_sku": p, "variant_sku": data["products"][p]["variants"][0], "is_published": "yes"}
               for p in sorted(data["published"])])  # fmt: skip
    files = ["01_products.csv", "02_images.csv", "03_publish.csv", "REPORT.md"]
    if setup:
        (RELEASE / "shop_setup.json").write_text(json.dumps(setup, indent=2, ensure_ascii=False), **TEXT)
        files.insert(3, "shop_setup.json")
    (RELEASE / "REPORT.md").write_text(report(data, setup), **TEXT)
    sums = [f"{hashlib.sha256((RELEASE / f).read_bytes()).hexdigest()}  {f}" for f in files]
    (RELEASE / "SHA256SUMS").write_text("\n".join(sums) + "\n", **TEXT)
    print(f"Wrote {RELEASE.relative_to(REPO)}/: {', '.join(files)}, SHA256SUMS")
    print(f"{len(data['products'])} products ({len(data['published'])} to publish), {len(data['variants'])} options, "
          f"{len(data['images'])} pictures. Open items: {RELEASE.relative_to(REPO)}/REPORT.md")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
