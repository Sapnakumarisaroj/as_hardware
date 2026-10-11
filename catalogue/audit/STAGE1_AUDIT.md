# Stage 1 audit — catalogue sources (11-Oct-2026, read-only)

Details, row by row: `stage1_audit.xlsx` (sheets: Summary, Issues, Products, Variants & prices, Images).
Re-run: `.venv\Scripts\python.exe -I catalogue\tools\audit_sources.py assets\as-hardware-images catalogue\audit\stage1_audit.xlsx`

No database rows, code or deployment were changed for this audit.

## What is in the folder

| Folder | Products | Variant rows | Images |
|---|---|---|---|
| Door Locks & Hardware | 12 | 50 | 13 |
| Glass Door Hardware | 19 | 29 | 19 |
| Hinges, Channels & Handles | 18 | 76 | 18 |
| Kitchen Systems & Accessories | 20 | 111 | 43 |
| Wardrobe & Bed Fittings | 20 | 46 | 20 |
| General Hardware & Tools | 80 | 112 | 76 |
| Power Tools & Accessories | 20 | 23 | 50 |
| Safety Tools & Workwear | 8 | 16 | 8 |
| Fevicol & adhesives | 14 | 36 | 14 |
| Plywood, MDF & HDHMR | 17 | 140 | 17 |
| **Total** | **228** (220 unique) | **639** (624 unique) | **278** |

Local database: 45 categories, 5 products (the Fevicol pilot drafts, unpublished, no variants yet), 5 images.

## Finding 1 — every workbook is a HomeRun export (blocks publishing)

Each file's first rows say *"Source: HomeRun (home-run.co) … Data captured 10-Oct-2026 (prices in INR, may change)"*.
The **Full Price List (all options with ₹ amount)** column and the price sheets hold **HomeRun's selling prices and
MRPs**, not AS Hardware's. "In Stock" is HomeRun's availability. Most descriptions are HomeRun's text, or just the product
name repeated (130 of 228).

The pictures came from HomeRun's website as well. Of the 298 image links in the sheets, 28 are files named as
ChatGPT-generated images and 8 are WhatsApp photos. Usage rights for all 278 pictures are **unconfirmed**.

## Finding 2 — the price data itself is consistent

- **611 of 639** variant rows match the "Full Price List" text exactly (option, selling price and MRP).
- **5 rows:** the price sheet has a decimal MRP (₹389.85, ₹550.85, ₹12.5, ₹728.57, ₹3,352.85) and the text shows it rounded.
  If imported, the exact sheet value would be kept.
- **23 rows have a selling price above MRP**, which the shop must not charge (the importer refuses these):
  Century Club Prime BWP Plywood (all 10 sizes), Greenply Gold 710 BWP (6), Greenply Ecotec MR 16mm (2),
  Ebco Roll Top Pro 600mm (2 finishes), Hillson Gumboots size 7, Taparia PVC tape 17mm, Bosch GWS 800 grinder.
- **135 rows have no MRP** ("Not listed"), for example all Safety items and the Virgo laminates. The database needs an MRP on
  every variant, and no MRP will be invented.
- **Bulk offers** (e.g. "2+ pcs: ₹3149") are on some rows. They are HomeRun's offers too.

## Finding 3 — duplicates

- 8 products appear in two files: 7 safety items (General Hardware **and** Safety Tools), and M-Seal Phataphat (General
  Hardware **and** Fevicol). Their 15 HomeRun SKUs repeat. Each would be imported once only.
- The Ebco Plate Basket and Ebco Thali Basket pictures are the same file, so neither picture can be relied on.
- 4 more pairs of identical image files (copies across folders). These are harmless, and each picture would be stored once.

## Finding 4 — image matching

| Result | Images | What happens |
|---|---|---|
| Exact filename = product name | 208 | Attach (as *unverified* until rights confirmed) |
| Likely (name truncated or misspelt) | 17 | Needs your OK, e.g. `Fevicol SH Adesive.webp` |
| Uncertain | 6 | Not attached, e.g. `Ebco Universal Magic Corner` vs Hettich product |
| No product in any sheet | 47 | Not used: no price data (Faber hoods, Makita saws, Dongcheng sanders, Ebco bins…) |

Products without any picture: *Ozone Glass Patch Fitting OPF-1* and *Taparia Line Tester 813*.

## Finding 5 — fields the website requires that are not in the source

- **GST rate:** a new product can't be saved without one, and no workbook has it. HSN codes are missing too.
- **AS Hardware SKU:** to be generated (pattern `ASH-<BRAND>-<MODEL>`, as in the Fevicol pilot). HomeRun SKUs are kept only
  in the audit trail.
- **Category:** the HomeRun product types (about 100) need mapping to the site's 45 categories. Some have no home yet:
  cleaners, water tanks, storage racks, waste bins, LED lights, laminates and liners.
- **Stock:** not in the source (HomeRun's "In Stock" is not yours).

## Decisions needed before Stage 3

1. **Prices.** Are the HomeRun prices the prices AS Hardware will charge? Or is there an AS Hardware price list?
   Without one, products can be imported as drafts with prices left blank ("awaiting price"), but none can be published.
2. **MRP missing (135 rows) and price above MRP (23 rows).** Options: supply MRPs from packaging or the supplier, or skip
   those variants. Showing a variant with no MRP would need a small code change.
3. **Pictures.** Do you have permission (from HomeRun or the manufacturers) to use them? If not, products stay
   unpublished until you replace them with your own or manufacturer photos. Should the 28 AI-named pictures be dropped?
4. **Descriptions.** Use name-only descriptions plus the manufacturer's published specs (as in the Fevicol pilot, checked
   per product)? HomeRun's description text would not be copied.
5. **GST rate and HSN per category.** Supply them, or approve rates looked up from CBIC per product (as done for Fevicol:
   18%, HSN 3506).
6. **Duplicates and categories.** Should the 7 safety items go under Safety Tools, and M-Seal under Sealants? Approve the
   new subcategories listed above.
7. **The 47 extra pictures with no price data.** Ignore them for now, or add those products later?
