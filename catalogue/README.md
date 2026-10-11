# Catalogue staging

## Full catalogue (all 10 HomeRun workbooks) — imported locally 11-Oct-2026, all unpublished

```
python -I catalogue/build_full_catalogue.py         # rebuilds staging/full_catalogue_*.csv and audit/import_report.xlsx
cd backend
python manage.py import_catalog ../catalogue/staging/full_catalogue_products.csv [--commit]
python manage.py import_catalog ../catalogue/staging/full_catalogue_pilot_prices.csv [--commit]
python manage.py import_product_images ../catalogue/staging/full_catalogue_images.csv --root ../assets/as-hardware-images [--commit]
```

Same SKUs on every run; re-running changes nothing. HomeRun prices are stored with `price_approved=no` (variant off
sale, product can't be published); rows without MRP or priced above MRP wait for a price. Pictures are `unverified`.
GST is 18% provisional and HSN blank. Row-by-row results and open items: `audit/import_report.xlsx`.
Stage 1 source audit: `audit/STAGE1_AUDIT.md`.

**Owner decisions applied 11-Oct-2026** (local database):
- Prices approved: MRP = Excel MRP, selling price = 95% of the Excel selling price (`build_price_approval.py` →
  `staging/full_catalogue_approved_prices.csv`, report `audit/price_approval_report.xlsx`). Options with no Excel MRP
  (121) or still above MRP after the 5% reduction (7) were left waiting.
- Folder pictures marked `owner_approved` (licence note records the HomeRun origin; rights not independently checked).
- 167 products with an approved price and a picture published (`staging/full_catalogue_publish.csv`); the rest are
  listed in `audit/not_published.csv`.
- Store BLR-01 (AS Hardware & Plywood, Kalkere, Bengaluru 560013) created without map coordinates or delivery zone
  (to be set once verified). Initial configured stock: 500 per approved option at BLR-01 (`staging/initial_stock_blr01.csv`,
  booked as inventory adjustments; not a physical count).
- GST/HSN per product from Notification 9/2025-Integrated Tax (Rate): `build_gst_hsn.py` → `audit/gst_hsn_review.xlsx`
  (status verified / rate verified / needs decision). The 9 "needs decision" products keep the 18% placeholder.
- Options still waiting for a price, with their Excel source rows: `audit/WAITING_OPTIONS.md`.


Sheets here are the source of truth for products being brought into the shop. They use the import columns from
`docs/CATALOG_IMPORT.md` and are imported with:

```
cd backend
python manage.py import_catalog ../catalogue/staging/fevicol_pilot_products.csv              # dry run
python manage.py import_catalog ../catalogue/staging/fevicol_pilot_products.csv --commit     # save
python manage.py import_product_images ../catalogue/staging/fevicol_pilot_images.csv --root ../assets/as-hardware-images [--commit]
```

Both commands are safe to run again. Everything is imported as an **unpublished draft**.

**Where the data comes from.** The spreadsheets in `assets/as-hardware-images/**` are an export of another retailer's
website (HomeRun, home-run.co). From them we take only *which products and pack sizes to list*. We do **not** use their
prices, MRPs, SKUs or description text. Product facts come from the manufacturer; descriptions are written for AS
Hardware; prices stay blank until the shop's own prices are entered.

## Fevicol pilot (5 products, 24 pack sizes) — status: imported locally, awaiting review

Source of facts: fevicol.in › Wood Work Adhesive and pidilite.com › Fevicol (Pidilite Industries), checked 10-Oct-2026.
GST 18% under HSN heading 3506 (prepared glues and adhesives, CBIC rate notification 9/2025-Integrated Tax (Rate)).

| AS SKU | Product | Subcategory | Pack sizes (variant SKUs `<SKU>-<size>`) | Picture |
|---|---|---|---|---|
| ASH-FEV-SH | Fevicol SH Synthetic Resin Adhesive | Wood Adhesives | 1, 2, 5, 10, 20, 30, 50 kg | `Fevicol SH Adesive.webp`, label checked |
| ASH-FEV-MARINE | Fevicol Marine Waterproof Adhesive | Waterproof Adhesives | 1, 2, 5, 10, 20, 50 kg | `Fevicol Marine Waterproof Adhesive.webp`, label checked |
| ASH-FEV-HEATX | Fevicol HeatX Heatproof Adhesive | Wood Adhesives ⚠ | 500 ml, 1 L, 5 L | `Fevicol HeatX Heatproof Adhesive.webp`, label checked |
| ASH-FEV-PROBOND | Fevicol Probond Adhesive for PVC & Acrylic | Wood Adhesives ⚠ | 1, 5, 10 kg ⚠ | `Pidilite Fevicol Probond Special Adhesive for PVC sheets & Tapes.webp`, label checked |
| ASH-FEV-HIPER | Fevicol Hi-Per Anti-Bubble Waterproof Adhesive | Waterproof Adhesives | 5, 10, 20, 30, 50 kg | `Fevicol HI-PER Anti-Bubble Waterproof Adhesive.webp`, label checked |

Full text (description, highlights, uses, specifications) is in `build_fevicol_pilot.py`.

### Needs your input before these can be published

1. **Prices and MRP** for all 24 pack sizes: fill the `mrp` and `price` columns of
   `staging/fevicol_pilot_products.csv` and import again (price must not be above MRP).
2. **Which pack sizes you stock.** The list follows the HomeRun export. Each size is on the manufacturer's list except
   **Probond 10 kg** (fevicol.in lists 500 g, 1 kg, 5 kg). Delete rows you don't sell before entering prices.
3. **Pictures:** all five are marked *unverified* (they came with the HomeRun export). Each shows one pack only.
   Confirm you may use them, or replace them with your own or manufacturer-supplied photos.
4. **Subcategory** for HeatX and Probond: placed under Wood Adhesives; move HeatX to Contact Adhesives if you prefer.
5. **HSN:** stored as the 4-digit heading 3506. Replace with the 8-digit code from your supplier invoice if you have it.
6. **Stock:** not set. Enter it per store when the variants exist.
7. **Not included (unverified):** installation steps, FAQs, warranty, shelf life, net weight per pack, technical data
   (viscosity, pH and similar figures appear only on marketplace listings, not on Pidilite's own pages).

### Differences from the HomeRun export (manufacturer wins)

- Marine: HomeRun says "water resistant up to 8 hours"; Pidilite says up to 5 days (boiling water up to 5 hours).
- Probond: HomeRun says "6 hr set"; Pidilite gives no setting time, so none is shown.
