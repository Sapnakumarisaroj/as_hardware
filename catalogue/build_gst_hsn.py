"""GST rate and HSN heading per product, from the official rate schedule.

    python -I catalogue/build_gst_hsn.py      # writes staging/gst_hsn.csv and audit/gst_hsn_review.xlsx

Source: Notification No. 9/2025-Integrated Tax (Rate) dated 17-9-2025 (as corrected 18-9-2025), in force from
22-9-2025. Schedule I = 5% IGST, Schedule II = 18% IGST (CGST + SGST: half each). Text checked from the copy on
CBIC's site: https://courier.cbic.gov.in/ECCS/advisory/2025/NOTIFICATION%20NO.%209_2025-INTEGRATED%20TAX%20(RATE)%20-1759486719.pdf

HSN is the 4-digit heading (enough on invoices for annual turnover up to Rs 5 crore; 6 digits above that).
Status per product:
  verified          the product clearly falls in that heading; the rate is that heading's schedule entry.
  rate verified     the plausible headings all carry the same rate; the heading should still be confirmed.
  needs decision    the plausible headings carry different rates: GST and HSN are left unchanged.
Footwear, garments and made-up textiles are 5% only up to Rs 2,500 per pair/piece (all ours are far below).
"""

import csv
import sys
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
N = "Notfn 9/2025-IT(R)"

# heading → (rate, schedule entry, heading text)
H = {
    "4410": (18, "Sch II 157", "Particle board and similar board of wood"),
    "4411": (18, "Sch II 158", "Fibre board of wood (MDF, HDF/HDHMR)"),
    "4412": (18, "Sch II 159", "Plywood, veneered panels and similar laminated wood"),
    "3506": (18, "Sch II 75", "Prepared glues and other prepared adhesives"),
    "3214": (18, "Sch II 56", "Glaziers' putty, resin cements, caulking compounds and other mastics"),
    "3919": (18, "Sch II 120", "Self-adhesive plates, sheets, film, tape, of plastics"),
    "3923": (18, "Sch II 124", "Articles for the conveyance or packing of goods, of plastics"),
    "3924": (18, "Sch II 125", "Tableware, kitchenware, other household articles, of plastics"),
    "4015": (18, "Sch II 141", "Gloves etc. of vulcanised rubber (other than surgical/examination)"),
    "6506": (18, "Sch II 212", "Other headgear (incl. safety helmets)"),
    "7317": (18, "Sch II 295", "Nails, tacks and similar articles, of iron or steel"),
    "7318": (18, "Sch II 296", "Screws, bolts, nuts and similar articles"),
    "7323": (18, "Sch II 302", "7323 9410 Ghamella"),
    "7314": (18, "Sch II 292", "Cloth, grill, netting and fencing, of iron or steel wire"),
    "7604": (18, "Sch II 333", "Aluminium bars, rods and profiles"),
    "8202": (18, "Sch II 362", "Hand saws; blades for saws of all kinds"),
    "8203": (18, "Sch II 363", "Files, pliers, pincers, metal cutting shears, pipe-cutters"),
    "8204": (18, "Sch II 364", "Hand-operated spanners and wrenches"),
    "8205": (18, "Sch II 365", "Hand tools n.e.s.; vices, clamps and the like"),
    "8206": (18, "Sch II 366", "Tools of two or more of 8202-8205, in sets for retail sale"),
    "8211": (18, "Sch II 371", "Knives with cutting blades and blades therefor"),
    "8301": (18, "Sch II 376", "Padlocks and locks of base metal; parts"),
    "8302": (18, "Sch II 377", "Base metal mountings and fittings for furniture, doors, windows"),
    "8467": (18, "Sch II 453", "Tools for working in the hand with self-contained motor"),
    "8504": (18, "Sch II 477", "Static converters (power supplies)"),
    "8536": (18, "Sch II 508", "Apparatus for making connections to electrical circuits"),
    "9015": (18, "Sch II 568", "Surveying and levelling instruments"),
    "9017": (18, "Sch II 570", "Measuring instruments for length (incl. measuring tapes)"),
    "9030": (18, "Sch II 579", "Instruments for measuring or checking electrical quantities"),
    "9403": (18, "Sch II 612", "Other furniture and parts thereof"),
    "9405": (18, "Sch II 614", "Luminaires and lighting fittings"),
    "3402": (18, "Sch II 67", "Washing and cleaning preparations"),
    "3403": (18, "Sch II 68", "Lubricating preparations, anti-rust preparations"),
    "3405": (18, "Sch II 70", "Polishes and creams for furniture, floors, glass"),
    "3307": (18, "Sch II 64", "Room deodorisers and other perfumery preparations"),
    "6401": (5, "Sch I 392", "Footwear of sale value not exceeding Rs 2500 per pair (chapter 64)"),
    "64": (5, "Sch I 392", "Footwear of sale value not exceeding Rs 2500 per pair (chapter 64)"),
    "61/62/63": (5, "Sch I 388-390", "Apparel / made-up textile articles not exceeding Rs 2500 per piece"),
}

V, R, D = "verified", "rate verified", "needs decision"
BOTH_18 = "8302 or 9403, both 18%"
# HomeRun product type → (heading, status, note). "" heading = not stored.
BY_TYPE = {
    "MR Grade Plywood": ("4412", V, ""),
    "BWP Marine Plywood": ("4412", V, ""),
    "BWP Marine Plywood (Flexible)": ("4412", V, ""),
    "Calibrated Plywood": ("4412", V, ""),
    "MDF Boards": ("4411", V, ""),
    "HDHMR Boards": ("4411", V, ""),
    "Boilo Boards": ("4412", R, "board construction not stated; 4410/4411/4412 are all 18%"),
    "Decorative Laminates & Liners": ("", R, "paper laminate 4823 or plastic 3921, both 18%; confirm on supplier invoice"),
    "General Wood Adhesive": ("3506", V, ""),
    "Waterproof & Heat Resistant Adhesive": ("3506", V, ""),
    "Instant Contact Adhesive": ("3506", V, ""),
    "Construction Adhesive": ("3506", V, ""),
    "Epoxy Adhesive": ("3506", V, ""),
    "Epoxy Tile Adhesive": ("3506", V, ""),
    "Instant Super Glues": ("3506", V, ""),
    "Sealant Putty": ("3214", V, ""),
    "Sealant Putties": ("3214", V, ""),
    "Silicone Sealants": ("3214", V, ""),
    "General Purpose Sealants": ("8205", R, "caulking gun: 8205 or 8424, both 18%"),
    "Adhesive Tapes": ("3919", V, ""),
    "Electrical Accessories": ("3919", V, "PVC insulation tape"),
    "Barricade Tapes": ("", R, "non-adhesive plastic tape 3920/3926, both 18%"),
    "Cupboard & Drawer Locks": ("8301", V, ""),
    "Cylindrical Door Locks": ("8301", V, ""),
    "Deadbolt & Latchbolt Locks": ("8301", V, ""),
    "Glass Patch Locks": ("8301", V, ""),
    "Tower Bolts & Stoppers": ("8302", V, ""),
    "Floor Springs & Hinges": ("8302", V, ""),
    "Glass Door Handles & Locks": ("8302", V, ""),
    "Glass Patch Fittings": ("8302", V, ""),
    "Sliding Door Kits": ("8302", V, ""),
    "Regular Close Cabinet Hinges": ("8302", V, ""),
    "Soft Close Cabinet Hinges": ("8302", V, ""),
    "Zero Protrusion & Corner Hinges": ("8302", V, ""),
    "Drawer Runners": ("8302", V, ""),
    "Telescopic Drawer Channels": ("8302", V, ""),
    "Cargo Clamps & Connectors": ("8302", V, ""),
    "Gola & Profile Handles": ("8302", R, "aluminium handle profile: 8302 or 7604, both 18%"),
    "Aluminium Shutter Profiles": ("7604", R, "7604 or 8302, both 18%"),
    "Installation Templates & Screw Kits": ("", R, "drilling template: 8205 or 9017, both 18%"),
    "Tandem Box Systems": ("8302", R, BOTH_18),
    "Bottle Pullouts": ("8302", R, BOTH_18),
    "Corner & Side Pullouts": ("8302", R, BOTH_18),
    "Magic Corners": ("8302", R, BOTH_18),
    "Pantry & Larder Units": ("8302", R, BOTH_18),
    "Rolling Shutter Systems": ("8302", R, BOTH_18),
    "Cutlery Inserts & Trays": ("3924", V, ""),
    "Anti-Skid Mats": ("", R, "plastic mat 3918 or 3926, both 18%"),
    "SS Kitchen Baskets": ("", D, "household steel article 7323 = 5% (Sch I 416) vs furniture fitting/part 8302/9403 = 18%"),
    "Wicker Baskets": ("", D, "basketware 4602 = 5% (Sch I 311) vs furniture fitting 8302 = 18%"),
    "Bed Lift Gas Pumps & Fittings": ("8302", R, "8302 (gas springs possibly 8412), both 18%"),
    "Cabinet Lift-Up Fittings": ("8302", R, "8302 or 8412, both 18%"),
    "Sliding & Bi-Fold Mechanisms": ("8302", V, ""),
    "Wardrobe Rails & Brackets": ("8302", V, ""),
    "Tie & Belt Racks": ("8302", R, BOTH_18),
    "Wardrobe Organisers": ("", R, "leather box 4202/4205 or 9403, all 18%"),
    "Ironing Board Pullouts": ("8302", R, BOTH_18),
    "LED Strip Lights": ("9405", V, ""),
    "Cabinet Light Drivers": ("8504", V, ""),
    "Aluminium Profiles & Diffusers": ("7604", R, "7604 or 9405 part, both 18%"),
    "Shutter Grills": ("", R, "aluminium article 7616 or 8302, both 18%"),
    "Shelf Supports & Stiffeners": ("8302", V, ""),
    "Push Open Fittings": ("8302", V, ""),
    "Angle Grinders & Cutters": ("8467", V, ""),
    "Drills & Drivers": ("8467", V, ""),
    "Rotary & Demolition Hammers": ("8467", V, ""),
    "Painting Accessories": ("8467", V, "hand-held electric mixer"),
    "Storage Racks & Shelving": ("9403", R, "9403 or 7308, both 18%"),
    "Waste Bins": ("3924", R, "3924 or 3926, both 18%"),
    "Pullout & Pedal Waste Bins": ("3924", R, "3924 or 3926, both 18%"),
    "Water Storage Tanks": ("3923", R, "HDPE drum 3923 (3925 for tanks), both 18%"),
    "Cutting Blades & Discs": ("8202", V, ""),
    "Hammers": ("8205", V, ""),
    "Hammers & Mallets": ("8205", V, ""),
    "Screwdrivers": ("8205", V, ""),
    "Spanners": ("8204", V, ""),
    "Pliers": ("8203", V, ""),
    "Pliers & Cutters": ("8203", V, ""),
    "Pipe Cutters": ("8203", V, ""),
    "Clamps": ("8205", V, ""),
    "Files & Utility Knives": ("8203", V, "file set"),
    "Cutting Tools": ("8211", V, "utility knife"),
    "Nails & Fasteners": ("7317", V, ""),
    "Measuring Tapes": ("9017", V, ""),
    "Spirit Levels": ("9015", V, ""),
    "Lubricants & Sprays": ("3403", V, ""),
    "Cable Glands & Lugs": ("8536", V, ""),
    "Electrical Tools": ("8203", V, "crimping tool"),
    "Bathroom Cleaners": ("3402", V, ""),
    "Surface Cleaners": ("3402", V, ""),
    "Trowels & Floats": ("8205", V, ""),
    "Painting Tools": ("8205", V, ""),
    "Concrete Screed Bar": ("8205", R, "8205 or 7616, both 18%"),
    "Wire Mesh & Jali": ("7314", V, ""),
    "Hand Protection": ("4015", V, ""),
    "Safety Helmets": ("6506", V, ""),
    "Gumboots": ("6401", V, "price below Rs 2500 per pair"),
    "Safety Shoes": ("", R, "chapter 64 footwear below Rs 2500 per pair = 5%; heading depends on upper material"),
    "Reflective Safety Jackets": ("", R, "apparel/made-up textile (61/62/63) below Rs 2500 per piece = 5%; heading to confirm"),
    "Safety Harnesses": ("", D, "textile harness 6307 = 5% (up to Rs 2500) vs other headings at 18%"),
}
TYPE_RATE = {"Safety Shoes": "64", "Reflective Safety Jackets": "61/62/63"}
BY_SKU = {  # product-level exceptions to the type rule
    "ASH-TAPAR-7CBE66": ("8205", V, "screwdriver"),
    "ASH-TAPAR-008C3D": ("8206", V, "screwdriver set"),
    "ASH-TAPAR-B10AE7": ("8204", V, "pipe wrench"),
    "ASH-TAPAR-F37ECA": ("8204", V, "adjustable spanner"),
    "ASH-TAPAR-067C65": ("8204", V, "spanner set"),
    "ASH-TAPAR-2AFC03": ("8211", V, "snap-off blade cutter knife"),
    "ASH-TAPAR-3B5AC5": ("8202", V, "hacksaw blade"),
    "ASH-TAPAR-FC6FEB": ("9030", R, "line tester: 9030 or 8205, both 18%"),
    "ASH-TAPAR-7D2054": ("9030", R, "line tester: 9030 or 8205, both 18%"),
    "ASH-DIVER-2C927E": ("3405", V, "furniture polish"),
    "ASH-DIVER-066D1D": ("3307", V, "room deodoriser"),
    "ASH-GEN-B5F383": ("7323", V, "iron ghamela, tariff item 7323 9410"),
    "ASH-GEN-E4D367": ("3924", R, "plastic pan 3924 or 3926, both 18%"),
    "ASH-SUPRE-BE18A5": ("", R, "plastic protection sheet 3920/3921, both 18%"),
    "ASH-GEN-310E59": ("", D, "HDPE tarpaulin: plastic 3926 = 18% vs textile tarpaulin 6306 = 5% (up to Rs 2500)"),
    "ASH-EBCO-89F467": ("7318", V, "screw kit"),
    "ASH-GEN-6E96FF": ("3214", R, "epoxy metal paste: 3214 or 3506, both 18%"),
}


def main():
    sys.path.insert(0, str(HERE))
    import build_full_catalogue as b

    products, _ = b.load_products()
    staged = {
        r["product_name"]: r["product_sku"]
        for r in csv.DictReader((HERE / "staging/full_catalogue_products.csv").open(encoding="utf-8"))
        if r.get("product_name")
    }
    rows, review = [], []
    for p in products:
        sku = b.PILOT.get(p["key"]) or staged[p["name"][:200]]
        heading, status, note = BY_SKU.get(sku) or BY_TYPE.get(p["type"], ("", D, "type not classified"))
        key = heading or TYPE_RATE.get(p["type"], "")
        rate, entry, text = H.get(key, (None, "", ""))
        if status == R and rate is None:
            rate, entry, text = 18, "Sch II", "every plausible heading is in Schedule II (18%)"
        if status == D:
            rate = None
        review.append({
            "product_sku": sku, "product": p["name"], "type": p["type"], "status": status, "GST %": rate,
            "HSN": heading, "basis": f"{N} {entry}: {text}" if rate is not None else "", "note": note,
        })  # fmt: skip
        if rate is not None:
            rows.append({"product_sku": sku, "gst_rate": str(rate), "hsn_code": heading})
    with (HERE / "staging/gst_hsn.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["product_sku", "gst_rate", "hsn_code"])
        w.writeheader()
        w.writerows(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "GST & HSN"
    cols = list(review[0])
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in review:
        ws.append([r[c] for c in cols])
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    wb.save(HERE / "audit/gst_hsn_review.xlsx")
    print(dict(Counter(r["status"] for r in review)), dict(Counter(r["GST %"] for r in review)),
          "with HSN", sum(1 for r in review if r["HSN"]))


if __name__ == "__main__":
    main()
