# REST API

Base URL: `/api/`. JSON only. The live OpenAPI 3 schema is the source of truth (validated with zero warnings):

- `GET /api/schema/` — OpenAPI (YAML, or `?format=json`)
- `GET /api/docs/` — Swagger UI
- `GET /api/redoc/` — ReDoc

Legend: ✅ implemented & tested · 🔜 planned (phase)

## Conventions
- **Auth:** `Authorization: Bearer <access JWT>`. The login/register endpoints that issue tokens arrive in **Phase 3**. Until then, APIs are exercised with tests, or with tokens minted locally.
- **Default permission:** authenticated. Public endpoints are marked *public*.
- **Roles:** `customer`, `store_staff`, `delivery_partner`, `admin` (superusers count as admin). *Staff* = admin or store_staff.
- **Pagination:** `?page=&page_size=` (max 100) → `{count, next, previous, results}`. Categories, brands, addresses and the cart are unpaginated.
- **Money:** decimal strings, e.g. `"1299.00"`. Never floats.
- **Server-side truth:** clients send IDs and quantities only. Prices, discounts, tax, delivery fee and totals are always recalculated by the server. Unknown fields such as `grand_total` are ignored.
- **Errors:**
  ```json
  { "error": { "code": "insufficient_stock", "message": "Only 3 unit(s) available.", "details": {"sku": "X", "available": 3} }, "request_id": "..." }
  ```
  Common codes: `validation_error` (400), `not_authenticated` (401), `permission_denied` (403), `not_found` (404),
  `insufficient_stock` / `invalid_transition` / `duplicate_review` / `duplicate_sku` (409), `invalid_coupon`,
  `coupon_expired`, `coupon_min_order`, `cart_empty`, `max_quantity_exceeded`, `product_unavailable` (400), `throttled` (429).
- Every response carries an `X-Request-ID` header.

## System
| Method | Path | Access | Status |
|---|---|---|---|
| GET | `/api/health/` | public | ✅ app, version, DB status (503 if the DB is down) |

## Catalog ✅ (Phase 4: customer discovery)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/categories/` | public | Top-level categories, each with `product_count` and nested `children` (subcategories with their own `product_count`). Unpaginated |
| GET | `/api/categories/{slug}/` | public | A top-level category **or** a subcategory. Subcategories include `parent_detail {id, name, slug}` |
| POST/PUT/PATCH/DELETE | `/api/categories/…` | admin | Delete is soft, refused if it has subcategories/products (409) |
| GET | `/api/brands/`, `/api/brands/{slug}/` | public | |
| POST/PUT/PATCH/DELETE | `/api/brands/…` | admin | Soft delete |
| GET | `/api/products/` | public | Paginated listing. Query parameters below. Adds `search {query, matched}` when `q` is used |
| GET | `/api/products/facets/` | public | Filter options + counts for the **same** parameters as the listing (see *Facets*) |
| GET | `/api/products/{slug}/` | public | Listing fields + `description`, `tags`, `gst_rate`, `hsn_code`, `max_order_quantity`, `is_returnable`, `variants[]`, `specifications[]`, `images[]` |
| POST | `/api/products/` | admin | Product + `variants[]` + `specifications[]` in one request (transactional) |
| PUT/PATCH | `/api/products/{slug}/` | admin | Variants upserted by `id`; specifications replaced |
| DELETE | `/api/products/{slug}/` | admin | Soft delete (past orders keep snapshots) |
| GET | `/api/products/{slug}/reviews/` | public | Approved reviews only, paginated |
| POST | `/api/products/{slug}/reviews/` | customer | `{rating 1–5, title?, body?}`. Requires a delivered purchase; one review per product |
| GET | `/api/search/suggest/?q=` | public | Type-ahead: up to 6 `products` (listing shape), 4 `categories` `{name, slug, parent_name}`, 4 `brands`. Fewer than 2 characters → empty lists |
| GET | `/api/search/recent/` | customer | Own recent searches `[{query, searched_at}]`, newest first (max 10 kept) |
| POST | `/api/search/recent/` | customer | `{query}` → 201 (de-duplicated case-insensitively; under 2 chars → 204, not stored) |
| DELETE | `/api/search/recent/` | customer | Clear own history (204) |

Admins see unpublished products on detail and with `?include_unpublished=true` on list/facets. Customers get 404 for unpublished, inactive or deleted products.

### Listing query parameters (`/api/products/` and `/api/products/facets/`)
All optional and combinable. Unknown or malformed values are ignored (never a 500).

| Parameter | Example | Meaning |
|---|---|---|
| `q` | `bosch drill`, `1.5 sq mm wire` | Search words (max 100 chars, 8 words). See *Search* |
| `category` | `electrical` | Category **or** subcategory slug. A top-level slug includes all its subcategories. Unknown slug → empty result |
| `subcategory` | `wires-cables` | Subcategory slug |
| `brand` | `voltline,drillco` | Brand slugs, comma = OR |
| `min_price`, `max_price` | `500`, `2000` | Bounds on the shown (cheapest active variant) selling price, inclusive |
| `rating` | `4` | Average rating ≥ value (products with no reviews are excluded) |
| `discount` | `25` | Discount ≥ value % |
| `availability` / `in_stock` | `in_stock` / `true` | Only products with stock at an active fulfilment store |
| `fast_delivery` | `true` | Stocked at a store that has an active delivery zone with fast delivery enabled |
| `featured` | `true` | `is_featured` products |
| `bestseller` | `true` | Products with at least one confirmed-or-later sale |
| `exclude` | `slug-a,slug-b` | Leave these product slugs out (used for "related products") |
| `spec_<key>` | `spec_power=650,800` | Specification filter on `ProductSpecification.key` (case-insensitive value match, comma = OR; different keys AND) |
| `ordering` | see below | Sort order |
| `page`, `page_size` | `2`, `24` | Pagination (`page_size` max 100) |

`ordering`: `relevance` (default when `q` is set), *(empty)* = featured first then name (default otherwise), `price`, `-price`, `newest`, `rating`, `discount`, `popular` (units sold), `name`. Unknown values fall back to the default. Every ordering ends with a unique tie-breaker, so pages never overlap.

### Listing item fields
`id, name, slug, sku, short_description, brand{id,name,slug}, category, subcategory, unit, price, mrp, discount_percent, discount_amount, stock_status, fast_delivery, variant_count, default_variant_id, is_featured, rating_avg, rating_count, image, image_alt`.

- `price`/`mrp`/`default_variant_id` come from the **cheapest active variant** ("from ₹X").
- `discount_percent`, `discount_amount`: computed with `Decimal` on the server, returned as strings.
- `stock_status`: `in_stock` · `low_stock` (1–5 units across stores) · `out_of_stock`. Per-store quantities are never exposed.
- `image`: absolute URL of the primary image, or `null` (the UI shows a fallback).

### Product detail: variants
Each variant: `id, sku, name, attributes{…}, mrp, price, discount_percent, discount_amount, weight_grams, length_mm, width_mm, height_mm, is_default, stock_status, fast_delivery, available_quantity`.
`available_quantity` is `null` unless stock is low (then the total units, for "Only 3 left"). Images carry an optional `variant` id: that variant's images are shown first when it is selected.

### Facets
```json
{ "total": 12,
  "categories": [{"slug": "wires-cables", "name": "Wires & Cables", "count": 5}],
  "brands": [{"slug": "voltline", "name": "VoltLine", "count": 4}],
  "price": {"min": "99.00", "max": "4100.00"},
  "ratings": [{"min": 4, "count": 3}, {"min": 3, "count": 6}],
  "discounts": [{"min": 10, "count": 8}, {"min": 25, "count": 2}, {"min": 50, "count": 0}],
  "availability": {"in_stock": 11, "fast_delivery": 7},
  "specifications": [{"key": "cross_sectional_area", "name": "Cross-sectional area", "unit": "sq mm",
                      "values": [{"value": "1.5", "count": 3}, {"value": "2.5", "count": 2}]}] }
```
- Each dimension is counted with every *other* active filter applied (picking a brand doesn't hide the other brands).
- `categories`: subcategories when browsing a top-level category, top-level categories otherwise (search), empty on a subcategory.
- `specifications`: only keys shared by at least 40 % of the results (with at least 2 distinct values) are offered, max 6 keys × 15 values. A drill listing therefore offers power/chuck size and a wire listing offers area/length. Selected keys always stay visible.

### Search
The listing's `q` goes through a pluggable backend (`CATALOG_SEARCH_BACKEND`, default `apps.catalog.search.KeywordSearchBackend`, portable across SQLite/PostgreSQL/MySQL):
- Words are lower-cased; sizes like `1.5` or `3/4` stay intact; stop words (`the`, `for`, `with`…) are dropped; simple plurals match (`drills` → `drill`).
- A word may match product name/SKU, brand, category/subcategory, tags, variant name/SKU, specification name/value, or description.
- Every word must match. If nothing matches all words, products matching any word are returned with `search.matched = "some_terms"` (the UI says so).
- Relevance weights: name 10, brand 6, category 5, tags/variant 4, spec 3, description 1, plus 20 when the whole phrase is in the name.
- Phase 13 adds a semantic/hybrid backend with the same `search()` contract, so this API and the frontend don't change.

## Addresses ✅ (own only)
| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api/addresses/` | First address becomes default. Phone accepts `+91 98765 43210` (stored as 10 digits). PIN = 6 digits |
| GET/PUT/PATCH/DELETE | `/api/addresses/{id}/` | Delete is soft. Deleting the default promotes another |
| POST | `/api/addresses/{id}/set-default/` | |

Other users' addresses return 404.

## Cart & wishlist ✅
| Method | Path | Notes |
|---|---|---|
| GET | `/api/cart/` | Lines with current price, `price_changed`, `available_quantity`, `in_stock`; `totals` (subtotal, mrp_total, discount_total, delivery_fee, tax_total, grand_total, savings_vs_mrp); `issues[]`; `can_checkout` |
| DELETE | `/api/cart/` | Empty the cart |
| POST | `/api/cart/items/` | `{variant_id, quantity}`. Adds or increments. Validates purchasable, `max_order_quantity` and stock (409) |
| PATCH | `/api/cart/items/{id}/` | `{quantity}`, re-validated |
| DELETE | `/api/cart/items/{id}/` | |
| POST | `/api/cart/coupon-preview/` | `{code}` → discount + totals against the current cart. Nothing is reserved |
| GET/POST | `/api/wishlist/` | POST `{product_id}` (idempotent) |
| DELETE | `/api/wishlist/{product_id}/` | |

Delivery fee: `DELIVERY_FEE` (default ₹40), free at or above `FREE_DELIVERY_MIN_ORDER` (default ₹499), after discounts.

## Orders ✅
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/orders/` | customer | `{address_id, payment_method: "cod"\|"online", coupon_code?, customer_note?}` → places the order from the cart (transactional; stock reserved at one store that can fulfil every line). COD orders auto-confirm. Online orders stay `pending` with a **mock** payment intent (`payments[0].client_payload`) until Phase 8 |
| GET | `/api/orders/` | customer: own · staff: all | `?status=` filter |
| GET | `/api/orders/{order_number}/` | owner/staff | Items (snapshots), status history, payments |
| POST | `/api/orders/{order_number}/cancel/` | owner | `{reason}`. Only while pending/confirmed/processing, else 409. Releases stock, voids uncaptured payments |
| POST | `/api/orders/{order_number}/transition/` | staff | `{status, note?}`. Validated by the state machine (409 on invalid). Side effects: cancel → release stock, picked_up → sale |

## Inventory ✅ (staff only)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/inventory/` | Filters: `store`, `sku`, `low_stock=true` |
| POST | `/api/inventory/` | `{store, variant, low_stock_threshold?, opening_quantity?}`. Opening stock is booked as a `purchase` movement |
| GET/PATCH | `/api/inventory/{id}/` | Only `low_stock_threshold` / `is_active` are editable. Quantities are read-only |
| POST | `/api/inventory/{id}/adjust/` | `{movement_type: purchase\|adjustment\|return, quantity, reason, reference?}`. Adjustments may be negative and need a reason. Never below zero (409) |
| GET | `/api/inventory/movements/` | Ledger. Filters: `inventory`, `type` |

## Planned 🔜
- **Auth** `/api/auth/` (Phase 3): register, login, token refresh, logout (blacklist), forgot/reset password, `me`.
- **Payments** (Phase 8): `/api/payments/{id}/verify/` (mock + optional Razorpay), webhooks, refunds.
- **Stores / delivery ETA** (Phase 9), **delivery partner** `/api/delivery/…` (Phase 10).
- **Admin dashboard APIs** `/api/admin/…` (Phase 11). Until then, use the Django admin at `/django-admin/`.
- **AI** `/api/ai/…` (Phases 12–19). **Notifications/support** (Phase 20).
