# Catalogue import / export

Add or update the whole catalogue from a spreadsheet: **one row per variant**. Rows that share a
`product_sku` are the variants of one product.

- Dashboard: **Products › Import / export** (`/admin/products/import`, administrators only). Choose the file,
  **Check file** (a dry run: every row is checked, nothing is saved), read the result, then **Import**.
- Shell: `python manage.py import_catalog products.xlsx` (dry run) and `... --commit`; `--sheet NAME` for a sheet other
  than the first; `--allow-demo` to also change demo rows.
- Export: dashboard buttons, `GET /api/admin/catalog/export/?format=xlsx|csv`, or
  `python manage.py export_catalog --output catalogue.xlsx` (`--include-demo`, `--include-deleted`). The export uses
  exactly the import columns, so it can be edited and imported again.
- Blank template: dashboard button, `GET /api/admin/catalog/template/?format=xlsx|csv`, or
  `python manage.py export_catalog --template --output blank.xlsx`. The Excel template has a "Columns" sheet that
  explains every column.

Code: `backend/apps/catalog/importer.py` (reading, validation, import) and `importer_export.py` (export, template).
API details: [API.md › Catalogue import / export](API.md#catalogue-import--export).

## The file

- `.xlsx` (first sheet unless one is named) or `.csv` saved as **UTF-8** ("CSV UTF-8" in Excel; `,` `;` or tab separated).
- At most 5 MB and 5000 rows. Blank rows are skipped. The first row is the header; column names are not case-sensitive
  and spaces become `_`.
- Only `product_sku` and `variant_sku` are required columns. **A column that is not in the file is never changed**, so
  a file with just `product_sku, variant_sku, price` updates prices only. A column that *is* in the file is applied as
  written: a blank optional cell clears that value (exceptions below).
- Unknown column names stop the import (typos would otherwise be ignored silently).

## Columns

| Column | What to enter |
|---|---|
| `product_sku` | Product (model) SKU. Rows with the same value are variants of one product. **Required.** |
| `product_name` | Product name (≤ 200 characters). Required for a new product. |
| `category` | One of the ten approved departments (`apps/catalog/taxonomy.py`), by name or slug, e.g. `Power Tools & Accessories` or `power-tools`. Required for a new product. |
| `subcategory` | An approved subcategory **of that department**, by name or slug, e.g. `Drills`. Blank = none. |
| `brand` | Brand name. A name that does not exist yet creates the brand. Blank = no brand. |
| `unit` | `piece`, `pack`, `box`, `m`, `coil`, `kg`, `l`, `bag`, `pair` or `set` (or the label, e.g. `Metre`). Blank = unchanged (new products: piece). |
| `gst_rate` | GST % included in the price, 0 to 40, e.g. `18`. Required for a new product. |
| `hsn_code` | HSN code, 4 to 8 digits. Format the column as text in Excel to keep leading zeros. |
| `max_order_quantity` | Most units of the product in one order. Blank = unchanged (new products: 50). |
| `short_description` | One-line summary (≤ 300 characters). |
| `description` | Full description. |
| `tags` | Search keywords separated by commas: `pvc, 1/2 inch`. |
| `specifications` | `Name=value` pairs separated by `;`, optional unit in brackets: `Thickness=18 [mm]; Grade=BWP`. Replaces all specifications of the product. |
| `is_published` | `yes` / `no`. Blank = unchanged (new products start unpublished). |
| `related_accessory`, `related_compatible`, `related_required`, `related_alternative`, `related_incompatible` | Product SKUs separated by commas (in the shop or in the same file). Replaces that kind of link for the product. |
| `variant_sku` | Variant SKU, unique across the shop. **Required on every row.** |
| `variant_name` | e.g. `2.5 sq mm, 90 m coil`. Blank for a simple product. |
| `attributes` | Variant options as `Name=value` pairs separated by `;`: `Size=2.5 sq mm; Colour=Red`. Names that match an option type of the product's category also become structured options (filters, variant picker). |
| `option:<Name>` | Any number of extra columns, one option each, e.g. a column `option:Colour` with `Red`. |
| `mrp` | MRP per unit in rupees, GST inclusive. Required for a new variant. |
| `price` | Selling price per unit, GST inclusive, not above the MRP. Required for a new variant. |
| `cost_price` | Purchase cost per unit, GST inclusive. Optional; used only for profit reports, never shown to customers. |
| `bulk_tiers` | `quantity:price` pairs, smallest quantity first: `10:95; 50:90`. Each price lower than the one before and than the normal price; quantities ≥ 2 and ≤ the order limit. Blank (with the column present) removes the tiers. |
| `stock` | Wanted **available** quantity per store code: `BLR-01:25; BLR-02:10`. Blank = stock unchanged. |

Numbers may contain `₹`, `%` and thousands separators (`₹1,250.50`); at most 2 decimal places.

## Rules

Everything is checked before anything is saved, and every problem is reported with its row, column and SKU:

- the category must be one of the approved departments, the subcategory one of its approved subcategories;
- price ≤ MRP; bulk tiers ascending in quantity, cheaper with quantity and below the price; GST 0–40; HSN 4–8 digits;
- store codes must exist (and not be demo stores); stock is a whole number ≥ 0;
- a variant SKU may appear only once in the file, and may not belong to another product; deleted products are refused
  (restore them in the dashboard first);
- product columns repeated on a product's later rows may be left blank, but where they are filled they must match the
  first row;
- a new product needs its name, category and GST rate; a new variant its MRP and price. Nothing is guessed.

**All or nothing:** the import runs in one database transaction. If any row fails — during the checks or while saving —
nothing at all is saved. A dry run performs the whole import and rolls it back, so its result (create / update /
unchanged per row, counts) is exactly what the real import will do.

**Upsert by SKU:** an existing product or variant SKU is updated, a new one is created. SKUs are stored upper-case.
Variants that exist in the shop but are not in the file are left alone (never deleted).

**Stock** is never written directly: the difference between the wanted and the current available quantity is booked
through `inventory.services.apply_movement` as an *adjustment* with reason "Catalogue import" (reference
`catalog_import` + batch id), so it appears in the stock ledger with the person who imported it.

**Demo data:** imports always create real rows (`is_demo` stays false). Demo products, brands and stores are refused
unless `--allow-demo` / `allow_demo=true` is given. The export leaves demo products out unless asked for.
`python manage.py purge_demo_data [--commit]` removes the demo seed: demo rows still referenced by orders, reviews or
quotes are archived (soft-deleted, switched off) instead of deleted; real rows are never touched.

**Pictures are not imported.** Upload them on the product page in the dashboard (product › Pictures). The importer never
downloads files from links in a spreadsheet (`ProductImage` needs a stored file, and copying pictures from other sites
needs permission).

**Spreadsheet formulas:** the export prefixes text starting with `=`, `+`, `-` or `@` with `'` so Excel does not run it;
the importer removes that `'` again. Excel formulas in an uploaded `.xlsx` are read as their saved values.

## Example

```csv
product_sku,product_name,category,subcategory,brand,gst_rate,specifications,is_published,variant_sku,variant_name,mrp,price,cost_price,bulk_tiers,stock
DR-500,Impact Drill 500W,Power Tools & Accessories,Drills,Bosch,18,Power=500 [W],yes,DR-500-STD,Standard,3200,2799,2100,10:2700; 25:2650,BLR-01:12
DR-500,,,,,,,,DR-500-KIT,With bits,3800,3299,,,BLR-01:4
```

(Example values only: enter your own prices, costs and stock.)
