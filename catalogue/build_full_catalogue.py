"""Builds the full-catalogue staging sheets from the HomeRun export in assets/as-hardware-images.

    python -I catalogue/build_full_catalogue.py

Writes (all re-generated on every run, same SKUs every time):
  staging/full_catalogue_products.csv      import_catalog sheet: every unique product and option
  staging/full_catalogue_pilot_prices.csv  option prices for the 5 Fevicol pilot products (prices only, so the
                                           pilot's checked descriptions are left untouched)
  staging/full_catalogue_images.csv        import_product_images map (every picture "unverified")
  audit/import_report.xlsx                 source row → result, duplicates, skipped rows, open items

What is taken from the export, and how:
- Which products and options to list, brand, product type and option names (facts in the listing itself).
- Prices: HomeRun's MRP and selling price are stored as a *reference only* (`price_approved=no`): the
  variant is off sale and the product can't be published until the owner approves or replaces the price.
  A row with no MRP, or a price above its MRP, is left "awaiting price" (no variant created) and reported.
  The exact price-sheet value is used (e.g. MRP 389.85), after checking it against the "Full Price List" text.
- Not taken: HomeRun's descriptions, bulk offers, stock, SKUs (kept in the report for tracing only).
- Descriptions are written here from the listing facts only (name, brand, type, options). GST is the
  shop default 18% and marked provisional in the report; HSN is left blank. Both need checking.
- Every product is imported unpublished. Every picture is "unverified" (rights not confirmed).
"""

import csv
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SOURCE = REPO / "assets" / "as-hardware-images"
STAGING, AUDIT = HERE / "staging", HERE / "audit"
CAPTURED = "10-Oct-2026"
PRICE_SOURCE = f"HomeRun (home-run.co) listing {CAPTURED}; not approved"
LICENCE = "Came with the HomeRun data export; usage rights not confirmed. Do not publish."
GST_DEFAULT = "18"

# Products already imported by the Fevicol pilot (build_fevicol_pilot.py): only their prices are added.
PILOT = {
    "fevicol sh adhesive": "ASH-FEV-SH",
    "fevicol marine waterproof adhesive": "ASH-FEV-MARINE",
    "fevicol heatx heatproof adhesive": "ASH-FEV-HEATX",
    "pidilite fevicol probond special adhesive for pvc sheets and tapes": "ASH-FEV-PROBOND",
    "fevicol hi per anti bubble waterproof adhesive": "ASH-FEV-HIPER",
}

# HomeRun product type → (department slug, subcategory slug or "" for the department only).
# Only the approved category tree (apps/catalog/taxonomy.py) is used; nothing new is created.
TYPE_MAP = {
    "Cupboard & Drawer Locks": ("door-locks-hardware", "door-locks"),
    "Cylindrical Door Locks": ("door-locks-hardware", "door-locks"),
    "Deadbolt & Latchbolt Locks": ("door-locks-hardware", "door-locks"),
    "Tower Bolts & Stoppers": ("door-locks-hardware", "door-hardware"),
    "Floor Springs & Hinges": ("glass-door-hardware", "floor-springs"),
    "Glass Door Handles & Locks": ("glass-door-hardware", "glass-door-handles"),
    "Glass Patch Fittings": ("glass-door-hardware", "patch-fittings"),
    "Glass Patch Locks": ("glass-door-hardware", "patch-fittings"),
    "Sliding Door Kits": ("glass-door-hardware", ""),
    "Regular Close Cabinet Hinges": ("hinges-channels-handles", "hinges"),
    "Soft Close Cabinet Hinges": ("hinges-channels-handles", "hinges"),
    "Zero Protrusion & Corner Hinges": ("hinges-channels-handles", "hinges"),
    "Drawer Runners": ("hinges-channels-handles", "drawer-channels"),
    "Telescopic Drawer Channels": ("hinges-channels-handles", "drawer-channels"),
    "Cargo Clamps & Connectors": ("hinges-channels-handles", "drawer-channels"),
    "Gola & Profile Handles": ("hinges-channels-handles", "cabinet-handles"),
    "Aluminium Shutter Profiles": ("hinges-channels-handles", ""),
    "Installation Templates & Screw Kits": ("hinges-channels-handles", ""),
    "SS Kitchen Baskets": ("kitchen-systems", "kitchen-baskets"),
    "Wicker Baskets": ("kitchen-systems", "kitchen-baskets"),
    "Magic Corners": ("kitchen-systems", "kitchen-tall-units"),
    "Corner & Side Pullouts": ("kitchen-systems", "kitchen-tall-units"),
    "Pantry & Larder Units": ("kitchen-systems", "kitchen-tall-units"),
    "Bottle Pullouts": ("kitchen-systems", "kitchen-accessories"),
    "Cutlery Inserts & Trays": ("kitchen-systems", "kitchen-accessories"),
    "Tandem Box Systems": ("kitchen-systems", "kitchen-accessories"),
    "Rolling Shutter Systems": ("kitchen-systems", "kitchen-accessories"),
    "Anti-Skid Mats": ("kitchen-systems", "kitchen-accessories"),
    "Bed Lift Gas Pumps & Fittings": ("wardrobe-bed-fittings", "bed-fittings"),
    "Cabinet Lift-Up Fittings": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Ironing Board Pullouts": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Push Open Fittings": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Shelf Supports & Stiffeners": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Shutter Grills": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Sliding & Bi-Fold Mechanisms": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Tie & Belt Racks": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Wardrobe Organisers": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Wardrobe Rails & Brackets": ("wardrobe-bed-fittings", "wardrobe-fittings"),
    "Aluminium Profiles & Diffusers": ("wardrobe-bed-fittings", ""),
    "Cabinet Light Drivers": ("wardrobe-bed-fittings", ""),
    "LED Strip Lights": ("wardrobe-bed-fittings", ""),
    "Angle Grinders & Cutters": ("power-tools", "grinders"),
    "Drills & Drivers": ("power-tools", "drills"),
    "Rotary & Demolition Hammers": ("power-tools", "drills"),
    "Safety Helmets": ("safety", "helmets"),
    "Safety Shoes": ("safety", "safety-shoes"),
    "Gumboots": ("safety", "safety-shoes"),
    "Reflective Safety Jackets": ("safety", "workwear"),
    "Hand Protection": ("safety", "gloves"),
    "Safety Harnesses": ("safety", ""),
    "Barricade Tapes": ("safety", ""),
    "Screwdrivers": ("general-hardware", "screwdrivers"),
    "Spanners": ("general-hardware", "spanners"),
    "Hammers": ("general-hardware", "hammers"),
    "Hammers & Mallets": ("general-hardware", "hammers"),
    "Measuring Tapes": ("general-hardware", "measuring-tools"),
    "Spirit Levels": ("general-hardware", "measuring-tools"),
    "Cutting Tools": ("general-hardware", "cutting-tools"),
    "Cutting Blades & Discs": ("general-hardware", "cutting-tools"),
    "Pliers & Cutters": ("general-hardware", "cutting-tools"),
    "Pipe Cutters": ("general-hardware", "cutting-tools"),
    "Files & Utility Knives": ("general-hardware", "cutting-tools"),
    "Nails & Fasteners": ("general-hardware", "fasteners"),
    "Sealant Putties": ("general-hardware", "sealants"),
    "Sealant Putty": ("general-hardware", "sealants"),
    "Silicone Sealants": ("general-hardware", "sealants"),
    "General Purpose Sealants": ("general-hardware", "sealants"),
    "General Wood Adhesive": ("fevicol", "fevicol-wood-adhesives"),
    "Waterproof & Heat Resistant Adhesive": ("fevicol", "fevicol-waterproof-adhesives"),
    "Instant Contact Adhesive": ("fevicol", "fevicol-contact-adhesives"),
    "Construction Adhesive": ("fevicol", ""),
    "MR Grade Plywood": ("plywood-mdf-hdhmr", "plywood"),
    "BWP Marine Plywood": ("plywood-mdf-hdhmr", "plywood"),
    "BWP Marine Plywood (Flexible)": ("plywood-mdf-hdhmr", "plywood"),
    "Calibrated Plywood": ("plywood-mdf-hdhmr", "plywood"),
    "Boilo Boards": ("plywood-mdf-hdhmr", "plywood"),
    "MDF Boards": ("plywood-mdf-hdhmr", "mdf"),
    "HDHMR Boards": ("plywood-mdf-hdhmr", "hdhmr"),
    "Decorative Laminates & Liners": ("plywood-mdf-hdhmr", ""),
}
FOLDER_DEPARTMENT = {
    "Door Locks & Hardware": "door-locks-hardware",
    "Glass Door Hardware": "glass-door-hardware",
    "Hinges, Channels & Handles": "hinges-channels-handles",
    "Kitchen Systems & Accessories": "kitchen-systems",
    "Wardrobe & Bed Fittings": "wardrobe-bed-fittings",
    "General Hardware & Tools": "general-hardware",
    "Power Tools & Accessories": "power-tools",
    "Safety Tools & Workwear": "safety",
    "favicol": "general-hardware",  # non-Fevicol adhesives (Araldite, Laticrete …); Fevicol types are mapped above
    "Plywood, MDF & HDHMR": "plywood-mdf-hdhmr",
}
# The Fevicol department is brand-led: only Fevicol-brand products go there.
FEVICOL_ONLY = {"fevicol"}
BRANDS = {
    "fevicol (pidilite)": "Fevicol", "araldite (pidilite)": "Araldite", "m-seal (pidilite)": "M-Seal",
    "masterlok (pidilite)": "Masterlok", "dongcheng": "Dongcheng", "unbranded": "", "generic": "",
}  # fmt: skip
# Image files that are the same picture as another product's (can't tell which product it shows).
AMBIGUOUS_PICTURES = {"Ebco Plate Kitchen Basket, SS304, 150mm (H) X 505mm (D), 6 X 20.webp",
                      "Ebco Thali Kitchen Basket, SS304, 200mm (H) X 505mm (D), 8 X 20.webp"}  # fmt: skip
# Near-name matches checked by eye (filename truncated / misspelt, same model code). Anything else
# that is not an exact name match is left out and reported.
CONFIRMED_NEAR = {
    "Europa Cylinderical Locks SS AB.webp": "Europa Cylindrical Locks SS/AB",
    "Ozone LOCK STRIKE BOX - OPL-2B STD SSS OZONE.webp": "Ozone Lock Strike Box - OPL-2B STD SSS",
    "Ozone W2G LOCK - OPL-4A-N-S STD SSS OZONE.webp": "Ozone W2G Lock - OPL-4A-N-S STD SSS",
    "Ozone_CORNER_LOCK_-_OPL-1E_STD_SSS_OZONE_pic_1_500x.webp": "Ozone Corner Lock - OPL-1E STD SSS",
    "Hettich Larder 6 Tier Frame with Baskets for 600mm (24) Cabinet Pantry Unit, 50Kg.webp":
        "Hettich Larder 6 Tier Frame with Baskets for 600mm (24\") Cabinet Pantry Unit, 50Kg (9346304+9347699)",
    "Ebco Door Stiffener HD for 1000-2700mm (up to 8.8ft) Height Doors, Grey, DSTF2-.webp":
        "Ebco Door Stiffener HD for 1000-2700mm (up to 8.8ft) Height Doors, Grey, DSTF2-HD-GR",
    "Ebco Light Adapter Series 2, 24V 24W Power Supply Unit for LED Lights, PSU2-2424-.webp":
        "Ebco Light Adapter Series 2, 24V 24W Power Supply Unit for LED Lights, PSU2-2424-WH",
    "Ebco Luminor 8C, Set of Aluminium Heat Sink Profile with Diffusor Profile, Length.webp":
        "Ebco Luminor 8C, Set of Aluminium Heat Sink Profile with Diffusor Profile, Length 3m, LUM8C1",
    "Evion Reflective Safety Jacket 1  50GSM.webp": "Evion Reflective Safety Jacket 1\" (Net and Fabric) - 50GSM",
    "Hillson_Dragon_Steel_Toe_Gumboots_15_Height.webp": "Hillson Dragon Steel Toe Gumboots, 15\" High",
    "Fevicol Grippo WG, Synthetic Resin Adhesive, 50Kg.webp": "Fevicol Grippo WG, Synthetic Resin Adhesive, 50 Kg",
    "Fevicol Nail Free Ultra High Strength Adhesive & Sealant, 435g.webp":
        "Fevicol Nail Free Ultra High Strength Adhesive & Sealant",
    "Pidilite Masterlok Synthetic Wood Adhesive, 50Kg.webp": "Pidilite Masterlok Synthetic Wood Adhesive, 50 Kg",
    "Archidply_Decor_Pure_Classic_MR_Plywood_HomeRun.webp": "Archidply Decor Pure Classic MR Plywood",
    "Greenply_Ecotec_MR_303_Plywood_HomeRun.webp": "Greenply Ecotec MR 303 Plywood",
}


PRICE_SHEETS = ("Price Chart (All Options)", "All Variants & Prices", "Pack-size Price Chart")


def norm(s) -> str:
    s = str(s or "").lower().replace("&", " and ").replace("°", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def money(v):
    if v in (None, "", "—", "-", "Not listed"):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return round(float(m.group().replace(",", "")), 2) if m else None


def fmt(v) -> str:
    return "" if v is None else (f"{v:.2f}".rstrip("0").rstrip(".") if v % 1 else str(int(v)))


def code(text: str, n: int) -> str:
    return hashlib.sha1(norm(text).encode()).hexdigest()[:n].upper()


def brand_code(brand: str) -> str:
    letters = re.sub(r"[^A-Z0-9]", "", brand.upper())
    return letters[:5] or "GEN"


def table(ws):
    rows = list(ws.iter_rows(values_only=True))
    head_at = next(i for i, r in enumerate(rows[:6]) if r and "Product Name" in [str(c).strip() if c else "" for c in r])
    head = [str(c).strip() if c else f"col{j}" for j, c in enumerate(rows[head_at])]
    out = []
    for i, r in enumerate(rows[head_at + 1 :], start=head_at + 2):
        d = dict(zip(head, r))
        if d.get("Product Name") and isinstance(d.get("#"), (int, float)):
            d["_row"] = i
            out.append(d)
    return out


PRICE_LINE = re.compile(r"^(?P<label>.*?):\s*₹\s?(?P<price>[\d,]+(?:\.\d+)?)(?:\s*\(MRP\s*₹\s?(?P<mrp>[\d,]+(?:\.\d+)?)\))?")


def full_price_list(text) -> dict[str, tuple]:
    """'label: ₹x (MRP ₹y)' lines (plywood: 'thickness → size: ₹x (MRP ₹y) | size: …') → {label: (price, mrp)}."""
    found = {}
    for line in str(text or "").splitlines():
        parts = [("", line)]
        if "→" in line:
            thick, rest = line.split("→", 1)
            parts = [(thick.strip() + " / ", p) for p in rest.split("|")]
        for prefix, part in parts:
            m = PRICE_LINE.match(part.strip())
            if m:
                found[norm(prefix + m["label"])] = (money(m["price"]), money(m["mrp"]) if m["mrp"] else None)
    return found


def option_label(v: dict) -> tuple[str, dict]:
    """(display label, attributes) of a price-sheet row."""
    if "Pack Size" in v:
        return str(v["Pack Size"]).strip(), {"Pack Size": str(v["Pack Size"]).strip()}
    if "Thickness / Variety" in v:
        thick, size = str(v["Thickness / Variety"]).strip(), str(v.get("Size") or "").strip()
        if size in ("", "—", "-", "None"):
            return thick, {"Variety": thick}
        key = "Thickness" if re.match(r"^\d", thick) else "Variety"
        return f"{thick} / {size}", {key: thick, "Size": size}
    label = str(v.get("Size / Variety") or "Standard").strip()
    return label, ({} if label == "Standard" else {"Option": label})


def describe(p: dict, labels: list[str]) -> tuple[str, str]:
    """Short and full description written from the listing facts only (no marketing claims)."""
    brand, ptype, name = p["brand"], p["type"], p["name"]
    kind = ptype.rstrip("s") if ptype and not ptype.endswith("ss") else ptype
    by = f"{brand} " if brand else ""
    real = [l for l in labels if l != "Standard"]
    short = f"{by}{kind}" + (f", {len(real)} options" if len(real) > 1 else "") + "."
    body = [f"{name}{'' if name.endswith('.') else '.'}"]
    body.append(f"Type: {ptype}." + (f" Brand: {brand}." if brand else ""))
    if real:
        body.append("Available options: " + "; ".join(real) + ".")
    return short[:300], "\n\n".join(body)


def load_products():
    products, by_key, dups = [], {}, []
    for f in sorted(SOURCE.rglob("*.xlsx")):
        folder = f.parent.name
        wb = load_workbook(f, read_only=True, data_only=True)
        prod_rows = table(wb["Products"])
        var_sheet = next(ws for ws in wb.worksheets if ws.title in PRICE_SHEETS)
        var_rows = table(var_sheet)
        by_name = defaultdict(list)
        for v in var_rows:
            by_name[v["Product Name"].strip()].append(v)
        text_col = next(c for c in prod_rows[0] if str(c).startswith("Full Price List"))
        for r in prod_rows:
            name = r["Product Name"].strip()
            key = norm(name)
            src = f"{f.relative_to(SOURCE).as_posix()} › Products row {r['_row']}"
            raw_brand = str(r.get("Brand") or "").strip()
            brand = BRANDS.get(raw_brand.lower(), raw_brand)
            ptype = str(r.get("Product Type") or "").strip()
            dept, sub = TYPE_MAP.get(ptype, (FOLDER_DEPARTMENT[folder], ""))
            if dept in FEVICOL_ONLY and brand != "Fevicol":
                dept, sub = "general-hardware", ""
            item = {
                "key": key, "name": name, "brand": brand, "type": ptype, "grade": str(r.get("Grade") or "").strip(), "folder": folder, "source": src,
                "dept": dept, "sub": sub, "text": full_price_list(r.get(text_col)), "variants": by_name.get(name, []),
                "var_sheet": f"{f.relative_to(SOURCE).as_posix()} › {var_sheet.title}",
            }
            if key in by_key:
                first = by_key[key]
                # Safety items listed under General Hardware too: keep the Safety listing.
                if first["dept"] != "safety" and item["dept"] == "safety":
                    products[products.index(first)] = item
                    by_key[key] = item
                    dups.append({"product": name, "kept": src, "dropped": first["source"]})
                else:
                    dups.append({"product": name, "kept": first["source"], "dropped": src})
                continue
            by_key[key] = item
            products.append(item)
    return products, dups


def build():
    products, dups = load_products()
    rows, pilot_rows, report_products, report_variants, problems = [], [], [], [], []
    skus = {}
    for p in products:
        pilot_sku = PILOT.get(p["key"])
        sku = pilot_sku or f"ASH-{brand_code(p['brand'])}-{code(p['name'], 6)}"
        if sku in skus and skus[sku] != p["key"]:
            raise SystemExit(f"SKU clash {sku}: {p['name']}")
        skus[sku] = p["key"]
        seen_labels, labels, stored, awaiting = {}, [], 0, 0
        var_out = []
        for v in p["variants"]:
            label, attrs = option_label(v)
            lk = norm(label)
            price, mrp = money(v.get("Selling Price (₹)")), money(v.get("MRP (₹)"))
            vrec = {
                "source": f"{p['var_sheet']} row {v['_row']}", "product": p["name"], "product_sku": sku,
                "option": label, "HomeRun SKU": v.get("SKU"), "HomeRun price": price, "HomeRun MRP": mrp,
                "HomeRun bulk offer": v.get("Bulk Price Offer") or "", "variant_sku": "", "result": "", "reason": "",
            }
            if lk in seen_labels:
                same = seen_labels[lk] == (price, mrp)
                vrec.update(result="skipped", reason="same option listed twice" + ("" if same else " WITH DIFFERENT PRICES"))
                if not same:
                    problems.append({"product": p["name"], "issue": "conflicting duplicate option", "detail": label})
                report_variants.append(vrec)
                continue
            seen_labels[lk] = (price, mrp)
            labels.append(label)
            if pilot_sku:
                vsku = f"{pilot_sku}-{re.sub(r'[^A-Z0-9]', '', label.upper())}"
                attrs = {"Pack Size": label.replace("Kg", "kg").replace("Ltr", "L")}
            else:
                vsku = f"{sku}-{code(label, 4)}"
            vrec["variant_sku"] = vsku
            # Cross-check the price sheet against the "Full Price List" text on the Products sheet.
            listed = p["text"].get(lk) or (next(iter(p["text"].values())) if len(p["text"]) == 1 and len(p["variants"]) == 1 else None)
            note = []
            if listed is None:
                note.append("not in Full Price List text")
            elif listed[0] != price or (listed[1] != mrp and not (listed[1] and mrp and abs(listed[1] - mrp) < 1)):
                note.append(f"Full Price List says ₹{fmt(listed[0])} / MRP {fmt(listed[1]) or '—'}")
                problems.append({"product": p["name"], "issue": "price sheet and Full Price List differ", "detail": f"{label}: {note[-1]}"})
            elif listed[1] != mrp:
                note.append(f"MRP {fmt(mrp)} in price sheet, shown rounded as {fmt(listed[1])} in Full Price List")
            if price is None:
                vrec.update(result="awaiting price", reason="no selling price in source")
            elif mrp is None:
                vrec.update(result="awaiting price", reason="no MRP in source (not invented)")
            elif price > mrp:
                vrec.update(result="awaiting price", reason=f"selling price ₹{fmt(price)} is above MRP ₹{fmt(mrp)}")
                problems.append({"product": p["name"], "issue": "price above MRP", "detail": f"{label}: ₹{fmt(price)} > MRP ₹{fmt(mrp)}"})
            else:
                vrec.update(result="stored, price not approved", reason="HomeRun price kept for review; off sale")
            if note:
                vrec["reason"] += "; " + "; ".join(note)
            ok = vrec["result"].startswith("stored")
            stored += ok
            awaiting += not ok
            var_out.append({
                "variant_sku": vsku, "variant_name": "" if label == "Standard" else label[:120],
                "attributes": "; ".join(f"{k}={str(val).replace(';', ',')}" for k, val in attrs.items()),
                "mrp": fmt(mrp) if ok else "", "price": fmt(price) if ok else "",
                "price_approved": "no" if ok else "", "price_source": PRICE_SOURCE if ok else "",
            })
            report_variants.append(vrec)
        if not p["variants"]:
            problems.append({"product": p["name"], "issue": "no price rows", "detail": p["source"]})
        short, desc = describe(p, labels)
        product_cols = {
            "product_sku": sku, "product_name": p["name"][:200], "category": p["dept"], "subcategory": p["sub"],
            "brand": p["brand"], "unit": "pack" if p["dept"] == "fevicol" else "piece", "gst_rate": GST_DEFAULT,
            "short_description": short, "description": desc,
            "tags": ", ".join(t for t in dict.fromkeys([p["brand"].lower(), p["type"].lower()]) if t),
            "specifications": "; ".join(
                f"{k}={str(v).replace(';', ',').replace('=', '-')}" for k, v in (("Product type", p["type"]), ("Grade", p["grade"])) if v
            ),
            "is_published": "no",
        }
        for i, v in enumerate(var_out):
            if pilot_sku:
                pilot_rows.append({"product_sku": sku, **v})
            else:
                rows.append({**(product_cols if i == 0 else {"product_sku": sku}), **v})
        if not var_out and not pilot_sku:
            problems.append({"product": p["name"], "issue": "no options", "detail": "not imported"})
        report_products.append({
            "source": p["source"], "product": p["name"], "AS SKU": sku, "department": p["dept"],
            "subcategory": p["sub"] or "(department only)", "brand": p["brand"] or "(none)",
            "options": len(var_out), "stored (price not approved)": stored, "awaiting price": awaiting,
            "pilot product": "yes" if pilot_sku else "", "pictures": 0, "GST": "18% provisional, HSN missing",
            "status": "draft (unpublished)",
        })
    images, image_report = build_images(products, skus, report_products)
    write_csv(STAGING / "full_catalogue_products.csv", rows)
    write_csv(STAGING / "full_catalogue_pilot_prices.csv", pilot_rows)
    write_csv(STAGING / "full_catalogue_images.csv", images)
    write_report(report_products, report_variants, dups, image_report, problems)
    print(f"products {len(report_products)} (of which pilot {sum(1 for r in report_products if r['pilot product'])}), "
          f"options {sum(r['options'] for r in report_products)}, stored {sum(r['stored (price not approved)'] for r in report_products)}, "
          f"awaiting {sum(r['awaiting price'] for r in report_products)}, duplicates dropped {len(dups)}, "
          f"pictures {len(images)}, problems {len(problems)}")


def build_images(products, skus, report_products):
    by_key = {p["key"]: p for p in products}
    sku_of = {key: sku for sku, key in skus.items()}
    rows, report, seen_hash = [], [], {}
    pilot_files = set()
    pilot_map = STAGING / "fevicol_pilot_images.csv"
    if pilot_map.exists():
        pilot_files = {r["file"] for r in csv.DictReader(pilot_map.open(encoding="utf-8"))}
    for img in sorted(SOURCE.rglob("*.webp")):
        rel = img.relative_to(SOURCE).as_posix()
        stem = norm(img.stem)
        base = re.sub(r"( \d{1,2}| copy)$", "", stem)
        key = stem if stem in by_key else base if base in by_key else norm(CONFIRMED_NEAR.get(img.name, ""))
        rec = {"file": rel, "product": "", "product_sku": "", "result": "", "reason": ""}
        digest = hashlib.sha256(img.read_bytes()).hexdigest()
        if img.name in AMBIGUOUS_PICTURES:
            rec.update(result="not used", reason="identical file is used for two different products")
        elif key not in by_key:
            rec.update(result="not used", reason="no product with this name in any workbook (no price data)")
        elif rel in pilot_files:
            rec.update(product=by_key[key]["name"], product_sku=sku_of[key], result="already attached", reason="Fevicol pilot")
        elif digest in seen_hash:
            rec.update(product=by_key[key]["name"], product_sku=sku_of[key], result="not used", reason=f"same file as {seen_hash[digest]}")
        else:
            seen_hash[digest] = rel
            sku = sku_of[key]
            first = not any(r["product_sku"] == sku for r in rows)
            if not first and stem == key:  # the exact-name picture is the main one
                for r in rows:
                    if r["product_sku"] == sku:
                        r["is_primary"] = "no"
            primary = first or stem == key
            rows.append({"product_sku": sku, "file": rel, "is_primary": "yes" if primary else "no",
                         "alt_text": by_key[key]["name"][:200], "source_type": "unverified", "licence": LICENCE})
            how = "exact name" if key in (stem, base) else "near name, checked"
            rec.update(product=by_key[key]["name"], product_sku=sku, result="attached (unverified)", reason=how)
        report.append(rec)
    counts = defaultdict(int)
    for r in rows:
        counts[r["product_sku"]] += 1
    for rp in report_products:
        rp["pictures"] = counts.get(rp["AS SKU"], 0) + (1 if rp["pilot product"] else 0)
    return rows, report


def write_csv(path: Path, rows: list[dict]):
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, columns)
        w.writeheader()
        w.writerows(rows)


def write_report(products, variants, dups, images, problems):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    n = lambda rows, k, v: sum(1 for r in rows if r[k] == v)  # noqa: E731
    for line in [
        ["Full catalogue import report", f"source: HomeRun export captured {CAPTURED}"],
        ["Unique products", len(products)],
        ["Duplicate product listings dropped", len(dups)],
        ["Options (variants)", sum(r["options"] for r in products)],
        ["Options stored with HomeRun price, NOT approved (off sale)", sum(r["stored (price not approved)"] for r in products)],
        ["Options awaiting price (no MRP / price above MRP)", sum(r["awaiting price"] for r in products)],
        ["Duplicate option rows skipped", n(variants, "result", "skipped")],
        ["Pictures attached (unverified)", n(images, "result", "attached (unverified)")],
        ["Pictures not used", n(images, "result", "not used")],
        ["Products with no picture", sum(1 for r in products if not r["pictures"])],
        ["Published", 0],
        [],
        ["Before publishing a product the owner must:"],
        ["1", "Approve or replace every option's MRP and price (dashboard › product › variant › 'Price approved', then 'On sale')."],
        ["2", "Confirm the picture rights or replace the pictures (Django admin › product images: source type)."],
        ["3", "Check GST rate (18% entered provisionally) and add the HSN code."],
        ["4", "Fill MRP and price for options awaiting price, then import the sheet again."],
    ]:
        ws.append(line)
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 100
    for title, recs in (("Products", products), ("Options", variants), ("Open items", problems),
                        ("Duplicates", dups), ("Pictures", images)):
        s = wb.create_sheet(title)
        if not recs:
            continue
        cols = list(recs[0])
        s.append(cols)
        for c in s[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="DDDDDD")
        for r in recs:
            s.append([r.get(c) for c in cols])
        for j, c in enumerate(cols, 1):
            s.column_dimensions[get_column_letter(j)].width = min(60, max(10, len(c) + 2, *(len(str(r.get(c) or "")) + 2 for r in recs[:200])))
        s.freeze_panes = "A2"
        s.auto_filter.ref = s.dimensions
    wb.save(AUDIT / "import_report.xlsx")


if __name__ == "__main__":
    build()
