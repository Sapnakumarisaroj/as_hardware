"""Owner review sheet for the options still waiting for a price (read-only: no database access).

    python -I catalogue/tools/build_review_sheet.py   # writes catalogue/audit/128_OPTIONS_FOR_MY_REVIEW.xlsx

Every value comes from the original Excel cells (workbook, sheet, row). The two "My …" columns are left blank.
"""

import ast
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.stdout.reconfigure(encoding="utf-8")
CATALOGUE = Path(__file__).resolve().parents[1]
REPO = CATALOGUE.parent
sys.path.insert(0, str(CATALOGUE))
import build_full_catalogue as b  # noqa: E402

COLUMNS = [
    "Serial Number", "Product Name", "Brand", "Main Category", "Subcategory",
    "Variant/Option Name", "Excel Workbook Name", "Excel Sheet Name", "Excel Row Number",
    "Original Selling Price", "Original MRP", "Problem Type", "My Corrected MRP", "My Approved Selling Price", "Notes",
]  # fmt: skip
MISSING, CONFLICT = "MRP REQUIRED", "PRICE/MRP CONFLICT"


def category_names() -> dict[str, str]:
    """slug → name from the approved taxonomy (parsed, so Django isn't needed)."""
    tree = ast.parse((REPO / "backend/apps/catalog/taxonomy.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "APPROVED_TAXONOMY")
    names = {}
    for key, children in ast.literal_eval(node.value).items():
        names[key[0]] = key[1]
        names.update(dict(children))
    return names


def main():
    waiting = load_waiting()
    products, _ = b.load_products()
    by_name = {p["name"]: p for p in products}
    cats = category_names()
    raw_brand = {}
    for f in b.SOURCE.rglob("*.xlsx"):
        for r in b.table(load_workbook(f, read_only=True, data_only=True)["Products"]):
            raw_brand.setdefault(r["Product Name"].strip(), r.get("Brand"))
    rows = []
    for w in waiting:
        p = by_name[w["product"]]
        v = next(v for v in p["variants"] if b.option_label(v)[0] == w["option"])
        workbook, sheet_name = p["var_sheet"].split(" › ")
        problem = MISSING if "no MRP" in w["note"] else CONFLICT
        rows.append({
            "Product Name": p["name"], "Brand": raw_brand.get(p["name"]) or "",
            "Main Category": cats.get(p["dept"], p["dept"]), "Subcategory": cats.get(p["sub"], "") if p["sub"] else "",
            "Variant/Option Name": w["option"], "Excel Workbook Name": workbook.rsplit("/", 1)[-1],
            "Excel Sheet Name": sheet_name, "Excel Row Number": v["_row"],
            "Original Selling Price": v.get("Selling Price (₹)"), "Original MRP": v.get("MRP (₹)"),
            "Problem Type": problem, "My Corrected MRP": None, "My Approved Selling Price": None,
            "Notes": "" if problem == MISSING else f"Even at 95% (₹{w['selling price (95%)']}) the price is above the MRP.",
            "_folder": workbook.rsplit("/", 1)[0],
        })  # fmt: skip
    missing = [r for r in rows if r["Problem Type"] == MISSING]
    conflicts = [r for r in rows if r["Problem Type"] == CONFLICT]
    assert (len(missing), len(conflicts), len(rows)) == (121, 7, 128), (len(missing), len(conflicts), len(rows))

    wb = Workbook()
    wb.remove(wb.active)
    for title, data in (("121 Missing MRP", missing), ("7 Price Conflicts", conflicts), ("All 128 Options", rows)):
        sheet(wb, title, data)
    out = CATALOGUE / "audit" / "128_OPTIONS_FOR_MY_REVIEW.xlsx"
    wb.save(out)
    check = load_workbook(out, read_only=True)
    counts = {ws.title: sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None) for ws in check.worksheets}
    print(out, counts)


def load_waiting() -> list[dict]:
    wb = load_workbook(CATALOGUE / "audit/price_approval_report.xlsx", read_only=True)
    rows = list(wb["Options"].iter_rows(values_only=True))
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:] if r[head.index("result")] == "waiting"]


def sheet(wb, title, data):
    ws = wb.create_sheet(title)
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9D9D9")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    fill = PatternFill("solid", fgColor="FFF2CC")
    for n, r in enumerate(data, 1):
        ws.append([n, *(r[c] for c in COLUMNS[1:])])
        for col in ("My Corrected MRP", "My Approved Selling Price"):
            ws.cell(row=n + 1, column=COLUMNS.index(col) + 1).fill = fill
    widths = [8, 55, 16, 26, 22, 34, 44, 26, 10, 14, 16, 20, 16, 18, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for col in ("Original Selling Price", "My Corrected MRP", "My Approved Selling Price"):
        for cell in ws[get_column_letter(COLUMNS.index(col) + 1)][1:]:
            cell.number_format = "#,##0.00"
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions


if __name__ == "__main__":
    main()
