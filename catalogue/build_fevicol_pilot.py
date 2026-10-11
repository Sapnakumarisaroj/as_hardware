"""Builds the Fevicol pilot staging sheets (product import + picture map) from facts verified on the
manufacturer's site, fevicol.in / pidilite.com (checked 10-Oct-2026). Descriptions are written for
AS Hardware; nothing is copied from the HomeRun export, and no HomeRun price or SKU is used.

    python catalogue/build_fevicol_pilot.py      # rewrites catalogue/staging/fevicol_pilot_*.csv

Prices stay blank: each variant row is "awaiting price" until the shop's own MRP and selling price are
filled in (see catalogue/README.md).
"""

import csv
from pathlib import Path

HERE = Path(__file__).parent / "staging"
COMMON = {
    "category": "Fevicol",
    "brand": "Fevicol",
    "unit": "pack",
    "gst_rate": "18",  # HSN 3506 prepared glues & adhesives: 18% (Sch. II, Notfn 9/2025-IT(R))
    "hsn_code": "3506",  # 4-digit heading; confirm the 8-digit code on the supplier invoice
    "is_published": "no",
}

PRODUCTS = [
    {
        "product_sku": "ASH-FEV-SH",
        "product_name": "Fevicol SH Synthetic Resin Adhesive",
        "subcategory": "Wood Adhesives",
        "short_description": "Pidilite's general-purpose synthetic resin wood adhesive for carpentry and lamination.",
        "description": (
            "Fevicol SH is Pidilite's synthetic resin adhesive for everyday woodworking. Carpenters use it to join "
            "and laminate plywood, solid wood, particle board, hardboard and MDF, and to fix laminates and veneers. "
            "It also bonds porous materials such as paper and cardboard.\n\n"
            "Pidilite describes it as heat and water resistant and suitable for all climatic conditions."
        ),
        "highlights": "Heat and water resistant\nSuitable for all climatic conditions\nHigh coverage\nEasy to use",
        "uses": (
            "Carpentry and furniture joinery\nLamination work\n"
            "Bonding plywood, wood, particle board, hardboard and MDF\nFixing laminates and veneers\n"
            "Porous materials such as paper and cardboard"
        ),
        "specifications": "Adhesive type=Synthetic resin; Manufacturer=Pidilite Industries Ltd.",
        "tags": "fevicol, sh, wood glue, white glue, synthetic resin, carpentry, lamination",
        "packs": ["1 kg", "2 kg", "5 kg", "10 kg", "20 kg", "30 kg", "50 kg"],
        "image": "Wood & Adhesives/favicol/Fevicol SH Adesive.webp",
    },
    {
        "product_sku": "ASH-FEV-MARINE",
        "product_name": "Fevicol Marine Waterproof Adhesive",
        "subcategory": "Waterproof Adhesives",
        "short_description": "Waterproof wood adhesive for lamination in kitchens, bathrooms and other damp areas.",
        "description": (
            "Fevicol Marine is Pidilite's waterproof woodworking adhesive for lamination in places that get wet, "
            "such as kitchens, bathrooms and wall units. It bonds plywood, wood, particle board, hardboard, MDF, "
            "laminates and veneers.\n\n"
            "Pidilite rates it for water resistance of up to 5 days and boiling-water resistance of up to 5 hours, "
            "with a setting time of 5 hours. Pidilite's coverage guide is about 7 laminate sheets per 5 kg."
        ),
        "highlights": (
            "Water resistance up to 5 days (manufacturer rating)\nBoiling-water resistance up to 5 hours\n"
            "Sets in 5 hours\nEasy to spread, high coverage"
        ),
        "uses": (
            "Lamination in kitchens, bathrooms and wall units\n"
            "Bonding plywood, wood, particle board, hardboard and MDF\nFixing laminates and veneers"
        ),
        "specifications": (
            "Setting time=5 [hours]; Water resistance=Up to 5 days; Boiling-water resistance=Up to 5 hours; "
            "Coverage=About 7 laminate sheets per 5 kg; Manufacturer=Pidilite Industries Ltd."
        ),
        "tags": "fevicol, marine, waterproof glue, kitchen, bathroom, lamination",
        "packs": ["1 kg", "2 kg", "5 kg", "10 kg", "20 kg", "50 kg"],
        "image": "Wood & Adhesives/favicol/Fevicol Marine Waterproof Adhesive.webp",
    },
    {
        "product_sku": "ASH-FEV-HEATX",
        "product_name": "Fevicol HeatX Heatproof Adhesive",
        "subcategory": "Wood Adhesives",
        "short_description": "Quick-bonding heatproof adhesive for lamination near heat, on vertical and curved surfaces.",
        "description": (
            "Fevicol HeatX is Pidilite's heatproof woodworking adhesive for lamination that will be exposed to heat. "
            "It bonds in 10 to 15 minutes and Pidilite rates it for heat resistance up to 170 °C.\n\n"
            "It resists the spring-back of laminates on curved surfaces and, according to Pidilite, does not need "
            "masking tape, clamping, nailing or pressing, which suits vertical lamination. Coverage is about 2 "
            "laminate sheets per litre."
        ),
        "highlights": (
            "Bonds in 10–15 minutes\nHeat resistance up to 170 °C (manufacturer rating)\n"
            "Resists laminate spring-back on curved surfaces\nNo masking tape, clamping, nailing or pressing needed"
        ),
        "uses": "Lamination on surfaces exposed to heat\nVertical lamination\nLaminating curved surfaces",
        "specifications": (
            "Bonding time=10–15 [minutes]; Heat resistance=Up to 170 [°C]; "
            "Coverage=About 2 laminate sheets per litre; Manufacturer=Pidilite Industries Ltd."
        ),
        "tags": "fevicol, heatx, heat x, heatproof, lamination, vertical lamination",
        "packs": ["500 ml", "1 L", "5 L"],
        "image": "Wood & Adhesives/favicol/Fevicol HeatX Heatproof Adhesive.webp",
    },
    {
        "product_sku": "ASH-FEV-PROBOND",
        "product_name": "Fevicol Probond Adhesive for PVC & Acrylic",
        "subcategory": "Wood Adhesives",
        "short_description": "Pidilite adhesive made for bonding PVC and acrylic laminates and PVC edge beading.",
        "description": (
            "Fevicol Probond is Pidilite's adhesive made for PVC and acrylic materials. Use it to bond PVC to "
            "acrylic laminate and to fix PVC edge beading to plywood or MDF.\n\n"
            "Pidilite describes the bond as strong and durable, highly heat resistant and able to withstand changing "
            "climatic conditions."
        ),
        "highlights": (
            "Made for PVC and acrylic materials\nStrong, durable bond\nHigh heat resistance\n"
            "Withstands changing climatic conditions"
        ),
        "uses": "PVC with acrylic laminate\nPVC edge beading on plywood\nPVC edge beading on MDF",
        "specifications": "Suitable for=PVC and acrylic; Manufacturer=Pidilite Industries Ltd.",
        "tags": "fevicol, probond, pro bond, pvc adhesive, acrylic, edge band, beading",
        "packs": ["1 kg", "5 kg", "10 kg"],
        "image": "Wood & Adhesives/favicol/Pidilite Fevicol Probond Special Adhesive for PVC sheets & Tapes.webp",
    },
    {
        "product_sku": "ASH-FEV-HIPER",
        "product_name": "Fevicol Hi-Per Anti-Bubble Waterproof Adhesive",
        "subcategory": "Waterproof Adhesives",
        "short_description": "Fast-tack waterproof adhesive that cuts bubble formation under large laminate sheets.",
        "description": (
            "Fevicol Hi-Per is Pidilite's anti-bubble, waterproof lamination adhesive. It is designed to reduce "
            "bubbles between plywood and laminate, especially with laminates thicker than 1 mm, and is suited to "
            "kitchen work.\n\n"
            "Pidilite gives a tack time of 6 to 8 seconds and a setting time of about 2 hours."
        ),
        "highlights": (
            "Reduces bubble formation under laminates\nFast tack in 6–8 seconds\nSets in about 2 hours\n"
            "Water resistant"
        ),
        "uses": "Lamination, especially laminates thicker than 1 mm\nKitchen lamination work",
        "specifications": "Tack time=6–8 [seconds]; Setting time=2 [hours]; Manufacturer=Pidilite Industries Ltd.",
        "tags": "fevicol, hi-per, hiper, anti bubble, waterproof, lamination, kitchen",
        "packs": ["5 kg", "10 kg", "20 kg", "30 kg", "50 kg"],
        "image": "Wood & Adhesives/favicol/Fevicol HI-PER Anti-Bubble Waterproof Adhesive.webp",
    },
]

PRODUCT_COLUMNS = [
    "product_sku", "product_name", "category", "subcategory", "brand", "unit", "gst_rate", "hsn_code",
    "short_description", "description", "highlights", "uses", "specifications", "tags", "is_published",
    "variant_sku", "variant_name", "attributes", "mrp", "price",
]  # fmt: skip


def pack_code(pack: str) -> str:
    return pack.upper().replace(" ", "")


def main() -> None:
    HERE.mkdir(exist_ok=True)
    with open(HERE / "fevicol_pilot_products.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, PRODUCT_COLUMNS)
        writer.writeheader()
        for product in PRODUCTS:
            for i, pack in enumerate(product["packs"]):
                row = {"product_sku": product["product_sku"], "variant_sku": f"{product['product_sku']}-{pack_code(pack)}"}
                if i == 0:  # product columns once; later rows of the same product may stay blank
                    row |= COMMON | {k: v for k, v in product.items() if k in PRODUCT_COLUMNS}
                row |= {"variant_name": pack, "attributes": f"Pack Size={pack}", "mrp": "", "price": ""}
                writer.writerow(row)
    with open(HERE / "fevicol_pilot_images.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, ["product_sku", "file", "is_primary", "alt_text", "source_type", "licence"])
        writer.writeheader()
        for product in PRODUCTS:
            writer.writerow(
                {
                    "product_sku": product["product_sku"],
                    "file": product["image"],
                    "is_primary": "yes",
                    "alt_text": f"{product['product_name']} pack",
                    "source_type": "unverified",
                    "licence": "Came with the HomeRun data export; usage rights not confirmed. Do not publish.",
                }
            )


if __name__ == "__main__":
    main()
