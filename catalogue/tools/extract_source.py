"""Reads the HomeRun export spreadsheets under assets/as-hardware-images and writes, per folder, the
*structure* only: product names, brand, product type, the option labels each product is sold in, and
candidate picture files. Prices, MRPs, SKUs and description text are deliberately NOT copied.

    python catalogue/tools/extract_source.py      # writes catalogue/source/<folder>.json
"""

import json
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "assets" / "as-hardware-images"
OUT = ROOT / "catalogue" / "source"
IMAGE_TYPES = {".webp", ".jpg", ".jpeg", ".png"}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def header_index(rows) -> int:
    return next(i for i, r in enumerate(rows) if r and r[0] == "#")


def sheet_rows(ws):
    rows = [r for r in ws.iter_rows(values_only=True)]
    i = header_index(rows)
    header = [str(h).strip() if h else "" for h in rows[i]]
    return [dict(zip(header, r)) for r in rows[i + 1 :] if r and r[2] and str(r[0]).strip().isdigit()]


def option_label(row: dict) -> str:
    for key in ("Size / Variety", "Pack Size"):
        if row.get(key):
            return str(row[key]).strip()
    parts = [row.get("Grade"), row.get("Thickness / Variety"), row.get("Size")]
    return " | ".join(str(p).strip() for p in parts if p)


def candidates(name: str, folder: Path, all_images: list[Path]) -> list[str]:
    key = norm(name)
    found = []
    for path in all_images:
        stem = norm(path.stem)
        if stem == key or (len(stem) >= 12 and (key.startswith(stem[:40]) or stem.startswith(key[:40]))):
            found.append(path)
    found.sort(key=lambda p: (p.parent != folder, p.name))
    return [p.relative_to(IMAGES).as_posix() for p in found]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_images = [p for p in IMAGES.rglob("*") if p.suffix.lower() in IMAGE_TYPES]
    for book in sorted(IMAGES.rglob("*.xlsx")):
        folder = book.parent
        wb = openpyxl.load_workbook(book, read_only=True, data_only=True)
        products = sheet_rows(wb.worksheets[0])
        variant_sheet = wb.worksheets[-1]
        variants = sheet_rows(variant_sheet)
        result, seen = [], {}
        for p in products:
            name = str(p["Product Name"]).strip()
            if norm(name) in seen:
                seen[norm(name)]["listed_twice"] = True
                continue
            entry = {
                "source_name": name,
                "brand": str(p.get("Brand") or "").strip(),
                "type": str(p.get("Product Type") or "").strip(),
                "group": str(p.get("Category") or "").strip(),
                "options": [],
                "stock_flags": [],
                "images": candidates(name, folder, all_images),
            }
            for v in variants:
                if norm(v["Product Name"]) == norm(name):
                    label = option_label(v)
                    if label and label not in entry["options"]:
                        entry["options"].append(label)
                    if str(v.get("In Stock", "")).strip().lower() != "yes":
                        entry["stock_flags"].append(label)
            seen[norm(name)] = entry
            result.append(entry)
        used = {i for e in result for i in e["images"]}
        folder_images = sorted(p.relative_to(IMAGES).as_posix() for p in folder.iterdir() if p.suffix.lower() in IMAGE_TYPES)
        data = {
            "folder": folder.relative_to(IMAGES).as_posix(),
            "workbook": book.name,
            "products": result,
            "unmatched_images": [i for i in folder_images if i not in used],
        }
        slug = re.sub(r"[^a-z0-9]+", "-", folder.name.lower()).strip("-")
        (OUT / f"{slug}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{slug}: {len(result)} products, {sum(len(e['options']) for e in result)} options, "
              f"{len(data['unmatched_images'])} unmatched images", file=sys.stderr)


if __name__ == "__main__":
    main()
