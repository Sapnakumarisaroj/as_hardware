# REST API

Base URL: `/api/`. JSON only. The live OpenAPI 3 schema is the source of truth (validated with zero warnings):

- `GET /api/schema/` — OpenAPI (YAML, or `?format=json`)
- `GET /api/docs/` — Swagger UI
- `GET /api/redoc/` — ReDoc

Legend: ✅ implemented & tested · 🔜 planned (phase)

## Conventions
- **Auth:** `Authorization: Bearer <access JWT>` from `/api/auth/login/` or `/api/auth/register/` (see *Auth & profile*).
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
| GET | `/api/products/` | public | Paginated listing. Query parameters below. Adds `search {query, matched}` when `q` is used (hybrid search adds `mode`, `related_terms` and per-product `match_reason`/`match_type`; see *Search*) |
| GET | `/api/products/facets/` | public | Filter options + counts for the **same** parameters as the listing (see *Facets*) |
| GET | `/api/products/{slug}/` | public | Listing fields + `description`, `tags`, `gst_rate`, `hsn_code`, `max_order_quantity`, `is_returnable`, `variants[]`, `specifications[]`, `images[]` |
| POST | `/api/products/` | admin | Product + `variants[]` + `specifications[]` in one request (transactional) |
| PUT/PATCH | `/api/products/{slug}/` | admin | Variants upserted by `id`; specifications replaced |
| DELETE | `/api/products/{slug}/` | admin | Soft delete (past orders keep snapshots) |
| GET | `/api/products/{slug}/reviews/` | public | Approved reviews only, paginated |
| POST | `/api/products/{slug}/reviews/` | customer | `{rating 1–5, title?, body?}`. Requires a delivered purchase; one review per product |
| GET | `/api/search/suggest/?q=` | public | Type-ahead: up to 6 `products` (listing shape; `match_reason` when found by meaning/related words), 4 `categories` `{name, slug, parent_name}`, 4 `brands`. Fewer than 2 characters → empty lists |
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
`id, name, slug, sku, short_description, brand{id,name,slug}, category, subcategory, unit, price, mrp, discount_percent, discount_amount, stock_status, fast_delivery, variant_count, default_variant_id, is_featured, rating_avg, rating_count, image, image_alt, offer`.

`offer` (Phase 6): the best live automatic offer targeting the product, `{id, name, badge, min_order_value}` or `null`.
It is informational: `price` is unchanged and the discount is applied in the cart.

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
The listing's `q` goes through a pluggable backend (`CATALOG_SEARCH_BACKEND`). Since Phase 13 the default is
`apps.catalog.semantic.backend.HybridSearchBackend`; it starts from the keyword search below and falls back to exactly
that result whenever its extra parts are switched off, unavailable or fail. Both are portable across SQLite/PostgreSQL/MySQL.

**Keyword** (`apps.catalog.search.KeywordSearchBackend`, Phase 4):
- Words are lower-cased; sizes like `1.5` or `3/4` stay intact; stop words (`the`, `for`, `with`…) are dropped; simple plurals match (`drills` → `drill`).
- A word may match product name/SKU, brand, category/subcategory, tags, variant name/SKU, specification name/value, or description.
- Every word must match. If nothing matches all words, products matching any word are returned with `search.matched = "some_terms"` (the UI says so).
- Relevance weights: name 10, brand 6, category 5, tags/variant 4, spec 3, description 1, plus 20 when the whole phrase is in the name.

**Hybrid** (Phase 13) adds, for products that exist and are visible: *related words* (what an everyday description,
Hindi/Hinglish phrase or typo means in catalogue words: "machine for drilling concrete" → drill, masonry drill bit;
"diwar me hole" → drill, wall plug; "hamer" → hammer) and *meaning* (cosine similarity of the query to each product's
stored vector, `SEMANTIC_EMBEDDER`). Scores are added, so exact names still rank first. When only some words matched,
accidental substrings are dropped ("ac" in "Hacksaw"). Filters, `ordering` and pagination apply exactly as before;
prices and stock always come from the database. Additive response fields (absent with plain keyword search):
- `search.mode = "hybrid"`, `search.related_terms[]` (the catalogue words used), `search.matched = "related"` when none of the customer's own words matched.
- per product `match_type` (`keyword` | `related` | `semantic`) and `match_reason` ("For “hole”: drill", "Showing “hammer” for “hamer”", "Similar to what you described"). The UI shows the reason only for `related`/`semantic`.

A query with no matching meaning returns an empty page, never invented products.

## Addresses ✅ (own only)
| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api/addresses/` | First address becomes default. Phone accepts `+91 98765 43210` (stored as 10 digits). PIN = 6 digits. Optional map pin: `latitude` + `longitude` (both or neither, 6 decimals; `null` removes it). With a pin, delivery distance and time are calculated from the exact spot; without one, from the PIN code (Phase 9) |
| GET/PUT/PATCH/DELETE | `/api/addresses/{id}/` | Delete is soft. Deleting the default promotes another |
| POST | `/api/addresses/{id}/set-default/` | |

Other users' addresses return 404.

## Cart & wishlist ✅
| Method | Path | Notes |
|---|---|---|
| GET | `/api/cart/` | Lines with current price, `unit_mrp`, `line_total`, `line_mrp_total`, `discount_percent`, `price_at_add` + `price_changed`, `available_quantity`, `in_stock`, `purchasable`, `brand_name`, `attributes`, `max_order_quantity`, `image`; `totals` (subtotal, mrp_total, discount_total = offer_discount + coupon_discount, delivery_fee, tax_total, grand_total, savings_vs_mrp); `offers` (`applied[]`: id, name, description, badge, discount, variant_ids · `missed[]`: id, name, badge, min_order_value, shortfall); `issues[]`; `can_checkout`. Cart totals include automatic offers; coupons are applied at checkout |
| DELETE | `/api/cart/` | Empty the cart |
| POST | `/api/cart/items/` | `{variant_id, quantity}`. Adds or increments. Validates purchasable, `max_order_quantity` and stock (409) |
| PATCH | `/api/cart/items/{id}/` | `{quantity}`, re-validated |
| DELETE | `/api/cart/items/{id}/` | |
| POST | `/api/cart/coupon-preview/` | `{code}` → coupon discount (after automatic offers) + totals against the current cart. Nothing is reserved |
| GET/POST | `/api/wishlist/` | POST `{product_id}` (idempotent) |
| DELETE | `/api/wishlist/{product_id}/` | |

Delivery fee: `DELIVERY_FEE` (default ₹40), free at or above `FREE_DELIVERY_MIN_ORDER` (default ₹499), after discounts.

## Offers & coupons ✅ (Phase 6)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/offers/` | public | Live automatic offers: `id, name, description, badge, min_order_value, ends_at, applies_to_everything, categories[{name, slug}], products[{name, slug}]`. Applied in the cart without a code |
| GET | `/api/coupons/available/` | customer | Coupons the store advertises (`show_in_checkout`) that this customer can still use, each checked against their cart: `code, description, badge, min_order_value, ends_at, applicable, discount` (if applicable), `message` (why not, e.g. "Add ₹120.00 more…"). Applicable first. Private coupons are never listed |

Offers are managed in Django admin only (no write API). Order of application: automatic offers (one per line, lowest
`priority` wins; minimum spend counted on the offer's own lines), then one coupon on the remaining amount. See
ARCHITECTURE.md → *Offers and coupons*.

## Checkout ✅ (Phase 5)
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/checkout/preview/` | customer | `{address_id?, coupon_code?}` → server-validated checkout state. Writes nothing, reserves nothing |

Response:
```json
{ "cart": { …same as GET /api/cart/… },
  "totals": { "subtotal": "800.00", "mrp_total": "1000.00", "discount_total": "152.00", "offer_discount": "80.00",
              "coupon_discount": "72.00", "delivery_fee": "0.00", "tax_total": "98.85", "grand_total": "648.00",
              "savings_vs_mrp": "352.00" },
  "offers": { "applied": [ { "id": 3, "name": "Tools week", "badge": "10% off", "discount": "80.00", … } ],
              "missed": [] },
  "address_id": 31,
  "coupon": { "code": "DEMO10", "description": "…", "discount": "72.00" },        // or null (computed after offers)
  "coupon_error": { "code": "coupon_min_order", "message": "Add ₹451.00 more…", "details": {…} },  // or null
  "delivery": { …delivery quote for the chosen address, see "Delivery & fulfilment"… },
  "blocking_issues": [ { "code": "address_required", "message": "Add or choose a delivery address." } ],
  "can_place_order": false,
  "payment_methods": [ { "value": "online", "label": "Mock online payment (development — no real money)", "test_mode": true },
                       { "value": "cod", "label": "Cash on delivery", "test_mode": false } ] }
```
`blocking_issues[].code`: `cart_empty`, `cart_item_unavailable` (stock/availability changed — fix in the cart),
`address_required`, `address_not_found`, `coupon_invalid`, `not_deliverable` (the address is outside every delivery
zone, or the stores serving it can't supply every line; `delivery.reason_code` says which).
`delivery` is the fulfilment plan for the chosen address (Phase 9). Without an address nothing is promised
(`eta_minutes: null`, `delivery_type: null`) and the fee uses the global rule; with one, `totals.delivery_fee` follows
the fee rule of the delivery zone.

## Orders ✅
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/orders/` | customer | Places the order from the cart. Body: `{address_id, payment_method: "cod"\|"online", coupon_code?, customer_note?, expected_total?}`. Header `Idempotency-Key: <8–64 chars [A-Za-z0-9_-]>` (or body `idempotency_key`). **201** new order · **200** + `Idempotent-Replayed: true` when the key was already used by this customer (returns that order, creates nothing) |
| GET | `/api/orders/` | customer: own · staff: all | Newest first, paginated. `?status=` filter. Items: `order_number, status, payment_method, payment_status, grand_total, item_count` (units), `item_names` (first 3), `image`, `estimated_delivery_at`, `delivery_message`, `delivery` (Phase 9, see "Order delivery data"), `created_at` |
| GET | `/api/orders/{order_number}/` | owner/staff | Snapshots of items (+`image`, `product_slug`, per-line `offer_discount`) and address, all totals incl. `offer_discount`, `coupon_discount` and `applied_offers[{id, name, badge, discount, skus}]`, `status_history`, `payments`, `refunds`, `can_cancel`, `can_retry_payment`, `delivery_message`. Phase 7: `can_return`, `return_window_ends_at`, `can_reorder`, `returns[]` (see Returns), per item `returnable_quantity` (0 outside the window) and `returned_quantity`. Phase 9: `store_name`, `delivery`, `shipments[]` (see "Order delivery data") |
| POST | `/api/orders/{order_number}/cancel/` | owner | `{reason}` (required). Only while `pending`/`confirmed`/`processing`, else 409 `invalid_transition`. Releases reserved stock, voids uncaptured payments, creates a **pending** Refund for captured payments, gives the coupon use back, and takes the job off a rider who was already assigned |
| POST | `/api/orders/{order_number}/shipments/{sequence}/delivery-code/` | owner | Phase 10. New delivery code for a shipment that is out for delivery; the old one stops working. At most one per `DELIVERY_OTP_RESEND_SECONDS` (409 `otp_too_soon`); not out for delivery → 409 `otp_not_needed`. Returns the order |
| GET | `/api/orders/{order_number}/shipments/{sequence}/proof/` | owner · staff of the store · admin | Phase 10. The photo taken at delivery (`image/jpeg`, `Cache-Control: private, no-store`). 404 until the shipment is delivered or when no photo exists |
| POST | `/api/orders/{order_number}/retry-payment/` | owner | New online payment attempt for a `pending` online order whose last attempt failed/was cancelled (409 otherwise) |
| POST | `/api/orders/{order_number}/transition/` | staff | `{status, note?}`. Validated by the state machine (409 on invalid). Side effects: cancel → release stock, picked_up → sale; the order's shipments follow. Return statuses (`return_requested`, `returned`, and leaving `return_requested`) are refused here (409 `invalid_transition`): they move only through the return endpoints. Phase 10: `picked_up`, `out_for_delivery`, `delivered` and `delivery_failed` are refused with 409 `rider_in_charge` while a delivery partner holds a job for the order (the rider's steps move it; reassign or unassign instead), and cancelling is refused with 409 `shipment_on_the_way` once part of the order has left the store. Stores whose own riders don't use the app keep using these steps |
| POST | `/api/orders/{order_number}/reorder/` | owner | **Buy again** (Phase 7). Adds the order's items to the cart at **today's** prices (never the old price). Each line is capped by current stock and the product's order limit, counting what is already in the cart. Returns `{added[], skipped[], cart}`; each line is `{sku, name, requested, added, reason}` and `skipped` lists lines added partly or not at all (`"No longer sold."`, `"Out of stock right now."`, `"Only N added (stock or order limit)."`, `"Your cart already has the most you can order."`). Works for any order status; a store manager viewing a customer's order gets 404 |
| POST | `/api/payments/{public_id}/verify/` | owner | `{payload: {…what the gateway widget returned…}}`. The server verifies it **with the gateway** and returns the updated order. **Razorpay:** `{razorpay_order_id, razorpay_payment_id, razorpay_signature}`: HMAC-SHA256(`order_id\|payment_id`, key secret) is checked, then the payment is fetched from Razorpay (order id, amount and currency must match; `authorized` → captured). `{cancelled: true}` when the customer closes the window. **Mock:** `{mock_signature (from client_payload), mock_outcome: "success"\|"failed"\|"cancelled"\|"pending"}`. Still processing at the gateway → the attempt stays `created` and the order is confirmed later by webhook/reconciliation. Repeating a successful verification is harmless. A closed attempt → 409 `payment_state_invalid`, unless the gateway confirms it was captured (a retry inside the Razorpay window after a failure). Gateway unreachable → 409 `payment_verification_unavailable`, with nothing changed |

Customers cannot update or delete orders (PUT/PATCH/DELETE → 405) or change status except by cancelling; other
customers' orders, payments and addresses return 404.

**Placement errors:** `cart_empty` (400), `insufficient_stock` (409; also when the stores that deliver to the address
can't supply every line), `not_deliverable` (400, `details.reason`: `out_of_zone` | `location_unknown`),
`product_unavailable` / `max_quantity_exceeded` (400), coupon codes (`invalid_coupon`, `coupon_expired`, `coupon_min_order`, `coupon_not_applicable`,
`coupon_exhausted`, `coupon_already_used`: 400), `totals_changed` (409, `details: {expected, grand_total}`: prices,
stock or coupon changed since the customer saw `expected_total`; nothing is created), address of another user (404).

**Payment/order states:**

| Event | Payment | Order `payment_status` | Order `status` |
|---|---|---|---|
| COD placed | `pending` (provider `cod`) | `pending` | `confirmed` |
| Online placed | `created` (+ `client_payload`) | `pending` | `pending` |
| Gateway success | `captured` | `paid` | `confirmed` |
| Gateway failure | `failed` (+ `failure_reason`) | `failed` | `pending` (retry allowed) |
| Customer closed gateway | `cancelled` | `pending` | `pending` (retry or cancel) |
| Order cancelled | uncaptured → `cancelled`; captured stays `captured` + Refund `pending` → submitted to the gateway | unchanged until the refund is processed | `cancelled` |
| Refund processed (Phase 8) | `partially_refunded` / `refunded` | `partially_refunded` / `refunded` | unchanged |
| Online order unpaid after `PAYMENT_EXPIRY_MINUTES` (30) | open attempts → `cancelled` (after asking the gateway) | unchanged | `cancelled` (stock released, customer notified) |
| Money captured after cancellation/expiry, a second paid attempt, or wrong amount | `captured` + automatic full Refund | unchanged | unchanged (never confirmed on it) |
| COD order delivered (Phase 8) | COD record → `captured` (cash collected) | `paid` | `delivered` |
| Delivery attempt failed (Phase 10) | unchanged | unchanged | `delivery_failed` → `assigned` when sent out again, or `cancelled` (undelivered goods restocked, captured money refunded) |

**Order statuses:** `pending → confirmed → processing → packed → assigned → picked_up → out_for_delivery → delivered`,
plus `delivery_failed` (Phase 10), `cancelled`, `return_requested`, `returned`. From `packed` onwards the order status
is derived from its shipments: `delivery_failed` if any shipment failed, otherwise the least advanced shipment; so an
order is `delivered` only when every shipment is.

## Delivery & fulfilment ✅ (Phase 9)
Every delivery time is **calculated** by the fulfilment engine (`apps/delivery`; rules in ARCHITECTURE.md →
*Fulfilment and delivery engine*). There is no fixed "60 minutes": `FAST_DELIVERY_MAX_MINUTES` is only the cutoff
below which an estimate counts as fast delivery.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/delivery/check/` | public | Delivery eligibility for a location. Indicative: for one in-stock item at each store that serves the location |
| GET | `/api/delivery/estimate/` | public | Delivery quote for one product: `variant_id` (required), `quantity` (default 1) + location. Unknown/unpublished variant → 404 |
| GET | `/api/delivery/cart-estimate/` | customer | Delivery quote for the signed-in customer's cart + location |
| GET | `/api/delivery/zones/` | public | Active delivery zones of stores that take orders, with their **effective** rules |
| GET | `/api/stores/availability/` | public | `variant_id` (required) + optional location. Which stores hold the product |
| GET | `/api/delivery/shipments/` | store manager (their stores) / admin | Shipments, paginated. `?scope=waiting` (default: need a rider, including failed ones), `active` (with a rider), `failed`, `delivered`, `all`; `?status=` |
| GET | `/api/delivery/shipments/{id}/eligible-partners/` | staff / admin | Riders who may carry it, best first |
| POST | `/api/delivery/shipments/{id}/assign/` | staff / admin | `{partner_id}` → 201 `{assignment_id, order_status, partner_id}`. Also sends a failed shipment out again |

The rider workflow and the rest of the staff endpoints are in "Delivery partner workflow" below.

**Location parameters** (query string; one of): `address_id` (a saved address of the signed-in customer; anonymous →
401, someone else's → 404) · `latitude` + `longitude` (both; optional `postal_code`) · `postal_code` (6 digits).
Anything else → 400. `location_precision` in the answer says what the estimate is based on: `exact` (map pin or
coordinates), `pin` (centre of the PIN code) or `unknown` (only the PIN string; served through a zone's PIN list).

**`GET /api/delivery/check/?postal_code=411038`**
```json
{ "serviceable": true, "postal_code": "411038", "location_precision": "pin",
  "fast_delivery_available": true, "label": "Delivery in 14 minutes", "fast_unavailable_reason": "",
  "message": "⚡ Fast delivery available · Delivery in 14 minutes",
  "stores": [ { "name": "Demo Store — Kothrud", "area": "Kothrud", "distance_km": 0.0,
                "fast_available": true, "eta_minutes": 14, "label": "Delivery in 14 minutes" } ] }
```
Not serviceable: `serviceable: false`, `stores: []`, `message: "We don't deliver to PIN 411014 yet."`.
Standard only: `fast_delivery_available: false`, `label: "Today, 4:30 PM – 6:30 PM"`,
`message: "🚚 Standard delivery · Today, 4:30 PM – 6:30 PM"`, and `fast_unavailable_reason` says why.

**Delivery quote** (`/delivery/estimate/`, `/delivery/cart-estimate/`, and `delivery` in the checkout preview):
```json
{ "available": true, "delivery_type": "fast", "fast_delivery_possible": true,
  "eta_minutes": 18, "label": "Delivery in 18 minutes", "message": "⚡ Fast delivery · Delivery in 18 minutes",
  "store_name": "Demo Store — Kothrud", "prep_minutes": 10, "distance_km": 0.9,
  "estimated_delivery_at": "2026-09-28T13:34:00+05:30",
  "window_start": "2026-09-28T13:34:00+05:30", "window_end": "2026-09-28T13:49:00+05:30",
  "fee": "0.00", "free_delivery_min_order": "499.00", "amount_to_free_delivery": "0.00",
  "fast_unavailable_reason": "", "location_precision": "exact", "reason_code": "",
  "shipments": [ { "sequence": 1, "store_name": "Demo Store — Kothrud", "store_area": "Kothrud", "line_count": 1,
                   "delivery_type": "fast", "eta_minutes": 18, "label": "Delivery in 18 minutes", "distance_km": 0.9 } ] }
```
| Field | Meaning |
|---|---|
| `available` | `false` = can't be delivered there; `reason_code` is `out_of_zone`, `location_unknown`, `insufficient_stock` or `cart_empty` and `message` explains it. No ETA fields are set |
| `delivery_type` | `fast` or `standard`. `null` when no location was given (stock-only answer) |
| `eta_minutes`, `label` | fast: minutes until delivery, `"Delivery in 38 minutes"`. standard: minutes until the window opens, label = the window, `"Tomorrow, 10:00 AM – 12:00 PM"` |
| `fast_unavailable_reason` | Set when the answer is standard: fast delivery not offered in the area · store closed · no delivery partner available · the calculated time is over the cutoff (`"Delivery would take about 74 minutes (fast delivery is up to 60)."`) |
| `window_start`, `window_end` | fast: estimated arrival … + `FAST_WINDOW_MINUTES`. standard: the delivery window |
| `prep_minutes` | Pick-and-pack time at the store (the largest, for several stores) |
| `store_name`, `shipments[]` | The fulfilment store; with `shipments.length > 1` the order ships from several stores and `eta_minutes` is the **latest** shipment's |
| `fee`, `free_delivery_min_order`, `amount_to_free_delivery` | The zone's fee rule (global rule when the zone sets none, or no location) |

**`GET /api/delivery/zones/`** → `[{id, name, store_name, store_area, city, radius_km, postal_codes[],
fast_delivery_enabled, fast_delivery_max_minutes, delivery_fee, free_delivery_min_order}]`. Blank zone settings are
shown as the global value that applies.

**`GET /api/stores/availability/`** → `[{store_name, store_area, city, kind, stock_status, delivers_to_location,
distance_km}]`. `stock_status` is `in_stock` / `low_stock` / `out_of_stock`: **exact quantities are never exposed**.
`delivers_to_location` and `distance_km` (straight line) are `null` without a location. Warehouses are not listed.

**Assignment.** `eligible-partners` → `[{partner_id, full_name, vehicle_type, same_store,
active_assignments, capacity, distance_km}]`: active, verified, `available`, below `max_active_assignments`, and
based at the store or currently within `DELIVERY_PARTNER_PICKUP_RADIUS_KM` of it. `assign` errors (409):
`invalid_delivery_state` (order not `confirmed`/`processing`/`packed`/`assigned`/`delivery_failed`, or the shipment
is already on its way), `already_assigned` (the shipment has an active assignment), `partner_unavailable` (offline,
at capacity, unverified or too far). Unknown shipment or partner, or a shipment of another manager's store → 404.
A rider can be assigned while the order is still being packed; when every shipment of a `packed` order has a rider
the order becomes `assigned`. Cancelling the order (or `assigned → packed`) cancels the jobs of riders who have not
picked up yet and frees them.

### Order delivery data
`delivery` on order list and detail:
```json
{ "type": "fast", "type_label": "Fast delivery", "fast": true,
  "eta_minutes": 18, "minutes_left": 11, "label": "Delivery in 11 minutes",
  "estimated_ready_at": "…", "estimated_delivery_at": "…", "window_start": "…", "window_end": "…" }
```
`eta_minutes` is the promise made when the order was confirmed; `minutes_left` counts down to `estimated_delivery_at`
(`null` once the order is delivered, cancelled or returned; `label` becomes `"Arriving any minute"` at 0). Standard
orders carry their window in `label`. Orders placed before Phase 9 have `type: null` and an empty `label`.
`delivery_message` is the same information as one sentence that follows the order status (`"⚡ Delivery in 18 minutes
(by about 1:34 PM)"`, `"🚚 Standard delivery · Today, 4:30 PM – 6:30 PM"`, `"Out for delivery · …"`, `"Delivered"`).
An online order is re-estimated from the moment it is **paid**.

`shipments[]` on order detail: `{sequence, store_name, store_area, delivery_type, distance_km, prep_minutes,
eta_minutes, estimated_ready_at, estimated_delivery_at, window_start, window_end, item_ids[]}` plus the delivery
progress (Phase 10):

| Field | Meaning |
|---|---|
| `status`, `status_label` | `pending` (waiting for a rider) · `assigned` · `picked_up` · `out_for_delivery` · `delivered` · `failed` · `cancelled` |
| `delivery_attempts`, `picked_up_at`, `out_for_delivery_at`, `delivered_at` | Progress of this shipment |
| `rider` | `{name (first name), vehicle, phone, status}` or `null`. `phone` is set only while the rider carries the goods (`picked_up`, `out_for_delivery`) |
| `delivery_code` | `{state, code, expires_at, can_request_new}`: the code to tell the rider at the door. **Only for the customer who placed the order, only while the shipment is out for delivery**; `null` otherwise (also for staff). `state`: `active` (then `code` is set) · `expired` · `locked` (too many wrong tries): ask for a new one |
| `amount_to_pay` | Cash on delivery: what to pay the rider for this shipment; `null` when nothing is due |
| `failure` | `{code, reason, failed_at, next_step}` when the last attempt failed. The rider's free-text note is not shown to the customer |
| `proof_available`, `received_by` | After delivery. The photo itself is fetched from `/api/orders/{n}/shipments/{sequence}/proof/` |

## Delivery partner workflow ✅ (Phase 10)
Rules in ARCHITECTURE.md → *Delivery partner workflow*. Delivery partners sign in like everyone else
(`POST /api/auth/login/`, role `delivery_partner`; accounts are created and verified by an admin).

### Rider (own jobs only)
Another rider's job → 404. Customers, store managers and admins → 403. Anonymous → 401.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/delivery/me/` | `full_name, email, phone, vehicle_type, vehicle_number, home_store_name, status, is_verified, is_active, max_active_assignments, active_assignments, cash_in_hand, last_location_at` |
| PATCH | `/api/delivery/me/` | `{status: "available" \| "offline"}`. Nothing else is writable (`busy` is set by the system). 409 `partner_not_verified`; 409 `active_delivery` while a job is active |
| POST | `/api/delivery/me/location/` | `{latitude, longitude}` → 204. Only the latest position is kept |
| GET | `/api/delivery/assignments/` | `?scope=active` (oldest first) \| `history`; `?kind=delivery` \| `return_pickup`. Paginated |
| GET | `/api/delivery/assignments/{id}/` | One job |
| POST | `/api/delivery/assignments/{id}/accept/` | `assigned → accepted` |
| POST | `/api/delivery/assignments/{id}/reject/` | `{reason}` (required). `assigned`/`accepted` → `rejected`; the shipment waits for a rider again |
| POST | `/api/delivery/assignments/{id}/pickup/` | `{latitude?, longitude?}`. `accepted → picked_up`. Delivery: at the store; needs a packed order (409 `order_not_packed`); the shipment's stock reservation becomes a sale. Return pickup: from the customer |
| POST | `/api/delivery/assignments/{id}/start/` | `picked_up → out_for_delivery`. Issues the customer's delivery code and notifies the customer. Deliveries only (409 `not_a_delivery`) |
| POST | `/api/delivery/assignments/{id}/proof/` | multipart `photo` (JPEG/PNG/WebP, ≤ 8 MB), `received_by?`. While `out_for_delivery` (return pickup: once collected). Replaces an earlier photo |
| GET | `/api/delivery/assignments/{id}/proof/` | The rider's own photo |
| POST | `/api/delivery/assignments/{id}/complete/` | `{otp, cod_collected?, cod_amount?, cod_method?: "cash" \| "upi", cod_reference?, received_by?, notes?, latitude?, longitude?}`. Delivery: `out_for_delivery → delivered`. Return pickup: `picked_up → delivered` (handed over at the store; no code, no cash) |
| POST | `/api/delivery/assignments/{id}/fail/` | `{reason, note?}`; `note` required for `other`. `picked_up`/`out_for_delivery` → `failed` (return pickup: also from `accepted`). `reason`: `customer_unavailable`, `wrong_address`, `customer_refused`, `payment_not_ready`, `damaged`, `vehicle_problem`, `other` |
| PATCH | `/api/delivery/assignments/{id}/notes/` | `{notes}` (≤ 500), while the job is active |
| GET | `/api/delivery/earnings/` | `delivered_count, total_earnings, today_earnings, last_7_days_earnings, today_delivered_count, failed_count, cash_in_hand, cash_deliveries_pending_handover` |

Every action answers with the job. There is no PUT/PATCH/DELETE on a job (405), and a rider has no access to orders,
prices, customers, inventory or any staff endpoint (403/404). Unknown fields in a request are ignored.

**The job** (`GET /api/delivery/assignments/{id}/`):
```json
{ "id": 7, "kind": "delivery", "kind_label": "Delivery to the customer",
  "status": "out_for_delivery", "status_label": "Out for delivery", "next_actions": ["proof", "complete", "fail"],
  "order_number": "OD260928ABCDEF", "order_status": "out_for_delivery", "payment_method": "cod",
  "shipment_sequence": 1, "return_number": null,
  "amount_to_collect": "1200.00",
  "cod": { "amount_due": "1200.00", "collected": false, "collected_amount": null, "method": null,
           "collected_at": null, "handed_over": false, "handed_over_at": null },
  "pickup": { "name": "Demo Store — Kothrud", "address": "…", "phone": "…", "latitude": "18.507400", "longitude": "73.807700",
              "map_url": "https://www.openstreetmap.org/?mlat=…", "directions_url": "https://www.openstreetmap.org/directions?to=…",
              "geo_uri": "geo:18.507400,73.807700?q=18.507400,73.807700" },
  "drop": { "name": "Asha Kumar", "phone": "9876543210", "address": "12 MG Road, Kothrud, Pune, 411038",
            "address_line1": "…", "area": "…", "landmark": "…", "city": "…", "postal_code": "…",
            "latitude": "…", "longitude": "…", "note": "Call before delivery", "map_url": "…", "directions_url": "…", "geo_uri": "…" },
  "items": [ { "name": "Impact Drill 650W", "variant": "", "sku": "DEMO-DRILL", "quantity": 2 } ],
  "otp_state": "active", "proof_uploaded": false, "proof_required": false, "received_by": "",
  "distance_km": "2.70", "earning_amount": "0.00", "delivery_notes": "",
  "assigned_at": "…", "accepted_at": "…", "picked_up_at": "…", "out_for_delivery_at": "…", "delivered_at": null,
  "failed_at": null, "failure_code": "", "failure_reason": "", "rejected_at": null, "reject_reason": "",
  "status_history": [ { "from_status": "", "to_status": "assigned", "note": "Assigned by store", "created_at": "…" } ] }
```
- `pickup` / `drop`: store → customer for a delivery, customer → store for a return pickup. The customer's name,
  phone, address and note are present only while the job is active; afterwards only `{area, city}`.
- Navigation uses free links: `geo_uri` opens the phone's own maps app, `map_url` / `directions_url` open
  OpenStreetMap. Without a map pin they search for the address text.
- `items` has names and quantities, never prices. `amount_to_collect` is the only money a rider sees.
- `otp_state`: `none` · `active` · `expired` · `locked` · `used`. **The code itself is never sent to the rider.**
- `next_actions` tells the app which buttons to show; the server checks every step regardless.

**Errors** (409 unless noted): `invalid_delivery_state` (step not allowed from the current status; `details.status`),
`order_not_packed`, `not_a_delivery`, `return_not_open`, `partner_inactive`; 400 `reason_required`, `note_required`,
`proof_required` (when `DELIVERY_PROOF_REQUIRED`), `proof_invalid`, `proof_too_large`.

**Delivery code (OTP).** Six digits, issued at `start`, valid `DELIVERY_OTP_TTL_MINUTES` (30), single use.
`complete` answers 400 with: `otp_invalid` (wrong code; the message says how many tries are left), `otp_locked`
(after `DELIVERY_OTP_MAX_ATTEMPTS` = 5 wrong codes even the right one is refused), `otp_expired`, `otp_not_issued`.
A wrong code is counted although the request fails. The customer gets a new code from their order page
(`…/delivery-code/`), which replaces the old one. A failed attempt destroys the code; the next attempt gets its own.

**Cash on delivery.** `amount_to_collect` is this shipment's share of the order total (its items after discounts;
the delivery fee travels with the first shipment; shares add up to the order total). `complete` needs
`cod_collected: true` and `cod_amount` **equal** to it: 400 `cod_not_collected`, `cod_amount_mismatch`
(`details.amount_due`), `cod_method_invalid`. The amount is compared, never stored as sent. Online-paid orders have
`amount_to_collect: null`. `cash` stays in the rider's `cash_in_hand` until the store records the handover; `upi` is
paid to the store directly and needs none. The order becomes `paid` when the whole order is delivered.

### Staff (their stores) and admin
| Method | Path | Notes |
|---|---|---|
| GET | `/api/delivery/shipments/{id}/` | Status, rider, COD, `items[]` and `assignments[]`: every rider's job on the shipment with its `status_history` (delivery history) |
| POST | `/api/delivery/shipments/{id}/reassign/` | `{partner_id, reason?}` → 201. Only before pickup. 409 `not_assigned`, `already_picked_up`, `same_partner`, `partner_unavailable` |
| POST | `/api/delivery/shipments/{id}/unassign/` | `{reason?}`. Only before pickup; the shipment waits for a rider again |
| POST | `/api/delivery/shipments/{id}/complete-without-otp/` | `{note (required), cod_collected?, cod_amount?, cod_method?, cod_reference?}`. Closes a delivery that is out for delivery when the customer can't show the code. Flagged (`completed_without_otp`) and audit-logged. Same COD rules |
| GET | `/api/delivery/shipments/{id}/proof/` | The delivery photo. Each view is audit-logged |
| GET | `/api/delivery/partners/` | Rider availability: `partner_id, full_name, phone, vehicle_type, home_store_name, status, is_verified, is_active, active_assignments, capacity, can_take_jobs, cash_in_hand, last_location_at`. `?status=offline\|available\|busy`. Managers see riders based at their stores |
| GET | `/api/delivery/cod/` | Cash-on-delivery collections, newest first, paginated. `?handed_over=true\|false`, `?partner=<id>`. `assignment_id, order_number, store_name, partner_id, partner_name, cod_amount_due, cod_collected_amount, cod_method, cod_reference, cod_collected_at, handed_over, cod_handed_over_at, handed_over_to, cod_handover_note` |
| POST | `/api/delivery/cod/{assignment_id}/handover/` | `{note?}`. The store received the rider's cash. 409 `cod_not_collected`, `cod_already_handed_over` |
| POST | `/api/returns/{return_number}/assign-pickup/` | `{partner_id}` → 201. Sends a rider to collect an **approved** return (409 `invalid_delivery_state` otherwise, `already_assigned`, `partner_unavailable`) |

Staff shipment rows: `id, order_number, order_status, payment_method, sequence, store_name, status, status_label,
delivery_type, distance_km, estimated_ready_at, estimated_delivery_at, delivery_attempts, picked_up_at,
out_for_delivery_at, delivered_at, failed_at, failure_reason, failure_note, assigned_partner, rider{assignment_id,
assignment_status, partner_id, full_name, phone, completed_without_otp}, cod{…}, proof_available, can_assign,
can_reassign`. Managers of another store get 404 for everything here.

**Proof-of-delivery photos** are stored outside the web-served media folder and have no URL. They are streamed only
by the three `proof` endpoints (rider: own job · customer: own delivered order · staff: their store), with
`Cache-Control: private, no-store`. Uploads are re-encoded on the server: metadata such as GPS position and phone
model is removed, the picture is scaled to at most 1600 px and saved as JPEG.

**Notifications:** rider `delivery.assigned`, `delivery.unassigned` (in-app); customer `order.out_for_delivery`
(never contains the code), `order.part_delivered`, `order.delivered`, `delivery.failed` (in-app + email).

## Returns ✅ (Phase 7)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/returns/` | customer: own · store manager: returns of their stores' orders (+ own) · admin: all | Newest first, paginated. `?status=` (a status, or `open` = requested + approved), `?q=` (return/order number, customer), `?store=` |
| GET | `/api/returns/{return_number}/` | as above | |
| POST | `/api/returns/` | order owner | `{order_number, reason, details?, items: [{order_item_id, quantity}]}`. `reason`: `damaged`, `defective`, `wrong_item`, `not_as_described`, `no_longer_needed`, `other` (needs `details`). **201** with the return. The refund amount is calculated by the server |
| POST | `/api/returns/{return_number}/cancel/` | owner | Only while `requested` (409 `return_state_invalid` afterwards) |
| POST | `/api/returns/{return_number}/approve/` | staff of the order's store / admin | `{note?}`. `requested` → `approved` |
| POST | `/api/returns/{return_number}/reject/` | staff / admin | `{note}` (**required**, shown to the customer). `requested`/`approved` → `rejected` |
| POST | `/api/returns/{return_number}/receive/` | staff / admin | `{note?, restock: true}`. `approved` → `received`. `restock: false` for damaged items (no stock movement). Records a **pending** Refund |

Return fields: `return_number, order_number, status (+status_label), reason (+reason_label), details, refund_amount,
refund_method (original_payment | manual), refund_method_label, refund_status (null until received), restocked,
decision_note, created_at, decided_at, received_at, cancelled_at, can_cancel, items[{order_item_id, sku, product_name,
variant_name, quantity, refund_amount, image}]`, and (Phase 10) `pickup`: `null`, or `{status, status_label,
rider_name, rider_phone (while the pickup is active), picked_up_at, failure_reason}` when the store sent a delivery
partner to collect the items (`POST /api/returns/{n}/assign-pickup/`, see "Delivery partner workflow"). The rider
brings the items to the store; the store still checks them and calls `receive`, which starts the refund.

**Rules.**
- Only `delivered` orders can be returned, within `RETURN_WINDOW_DAYS` (default 7) of `delivered_at`, and only products
  with `is_returnable`. One request per order may be open at a time (409 `return_open`); the order is
  `return_requested` meanwhile.
- Partial returns are allowed. After a partial return is received, the order goes back to `delivered` and the remaining
  units can still be returned within the window. Once every unit has been received, the order becomes `returned`.
  A rejected or cancelled request also returns the order to `delivered`.
- **Refund** = what the customer paid for those units: line total, minus the line's offer discount, minus its pro-rata
  share of the coupon (spread over post-offer amounts, like GST). Cumulative rounding makes the returns of a whole line
  add up exactly to what was paid for it. The delivery fee is not refunded. Online orders refund to the captured
  payment (`original_payment`); COD orders get a `manual` refund recorded against the COD payment. Refunds stay
  `pending` until processed: online refunds go to the gateway automatically, COD refunds wait for staff to record them
  (see Payments & refunds).
- Errors: `order_not_delivered` / `return_open` / `return_state_invalid` (409); `return_window_closed`,
  `quantity_not_returnable`, `invalid_item`, `invalid_quantity`, `details_required`, `note_required` (400); another
  customer's order or return → 404; a customer calling approve/reject/receive → 403; a manager of another store → 404.
- Customer notifications (in-app; email as well from `approved` onwards): `return.requested`, `return.approved`,
  `return.rejected`, `return.received`.

## Payments, webhooks & refunds ✅ (Phase 8)
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/payments/webhooks/{provider}/` | gateway (no login) | Only the configured `PAYMENT_PROVIDER` (others → 404). **Razorpay:** header `X-Razorpay-Signature` = HMAC-SHA256(raw body, `RAZORPAY_WEBHOOK_SECRET`), de-duplicated by `X-Razorpay-Event-Id`. Events: `payment.captured`, `order.paid`, `payment.authorized` (captured), `payment.failed`, `refund.processed`, `refund.failed`; others are stored as `ignored`. Bad signature → 400 `invalid_webhook` (nothing stored). Each event is applied **once**: a redelivery → 200 without side effects (`deliveries` is counted). A processing error → 500 so the gateway redelivers. Not throttled. **Mock:** `X-Mock-Signature` = HMAC-SHA256(body, `SECRET_KEY + ":mock-webhook"`), `X-Mock-Event-Id`, same body format |
| GET | `/api/payments/refunds/` | store manager (their stores) / admin | `?status=pending\|processed\|failed`, `?q=` (order number, customer, reference), `?store=`. Fields: `public_id, order_number, payment_provider, customer_name, store_name, amount, status, reason, is_manual, provider_refund_id, attempts, failure_reason, manual_reference, created_at, processed_at` |
| POST | `/api/payments/refunds/{public_id}/mark-processed/` | staff / admin | `{reference}` (required: UPI/bank ref or cash receipt). For **COD refunds** (`is_manual`), or gateway refunds that **failed** and were paid another way. A pending gateway refund → 409 `refund_state_invalid` |
| POST | `/api/payments/refunds/{public_id}/retry/` | staff / admin | Failed gateway refund → pending again with a **new** gateway reference and queued. Anything else → 409 |

**Refund lifecycle.** Created `pending` (cancellation of a paid order, return received, late/duplicate/mismatched
payment), then a `payments.process_refund` job submits it to the gateway. Every submission carries the refund's
`provider_reference`, and Razorpay is first asked for an existing refund with that reference, so a retry after a
timeout never refunds twice. Result: `processed` (payment and order move to `partially_refunded`/`refunded`, customer
notified `refund.processed`), `failed` (audit-logged; staff retry or pay manually), or still `pending` at the
gateway (polled by `run_jobs` every 15 min and by `refund.*` webhooks). Temporary gateway errors retry with backoff.
Refunds can never exceed the captured amount (`refund_exceeds_payment`). Customers see each refund on the order
(`refunds[]`: `status`, `manual`, `processed_at`).

**Background (`python manage.py run_jobs`, cron every 5 min; `BACKGROUND_JOBS_MODE=inline` also runs jobs right after
commit):** submit queued refunds · ask the gateway about online attempts left open ≥ `PAYMENT_RECONCILE_AFTER_MINUTES`
(recovers payments whose confirmation never arrived) · expire unpaid online orders after `PAYMENT_EXPIRY_MINUTES`
(the gateway is asked first; an order paid at the last minute is confirmed instead) · poll pending gateway refunds ·
log consistency issues. `python manage.py payments_check` lists orders/payments/refunds that disagree (exit code 1).

## Inventory ✅ (staff only)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/inventory/` | Filters: `store`, `sku`, `low_stock=true`, `q` (SKU, product, variant or store name), `stock=out\|low\|ok` |
| POST | `/api/inventory/` | `{store, variant, low_stock_threshold?, opening_quantity?}`. Opening stock is booked as a `purchase` movement |
| GET/PATCH | `/api/inventory/{id}/` | Only `low_stock_threshold` / `is_active` are editable. Quantities are read-only |
| POST | `/api/inventory/{id}/adjust/` | `{movement_type: purchase\|adjustment\|return, quantity, reason, reference?}`. Adjustments may be negative and need a reason. Never below zero (409) |
| GET | `/api/inventory/movements/` | Ledger. Filters: `inventory`, `type` |

## Auth & profile ✅ (Phase 3)
`POST /api/auth/register/` (always role `customer`) · `POST /api/auth/login/` · `POST /api/auth/token/refresh/`
(rotating) · `POST /api/auth/logout/` (blacklists the refresh token) · `POST /api/auth/password/forgot|reset|change/` ·
`GET /api/auth/me/` · `GET/PATCH /api/profile/`, `POST /api/profile/avatar/`, `POST /api/profile/deactivate/` ·
admin only: `/api/admin/users/`. Login/register return `{access, refresh, user}`. See `/api/docs/` for bodies.

## Business dashboard ✅ (Phase 11, `/api/admin/…`)
The React dashboard at `/admin` uses these endpoints plus the staff endpoints of earlier phases (orders `transition`,
inventory, shipments, COD, returns, refunds). **Roles:** `admin` may read and change everything; a `store_manager`
reads the staff sections for the stores assigned to them (`Store.managers`) and changes only what runs their store;
customers and delivery partners get **403** on every path here. A manager asking for another store (`?store=`, an
order, a shipment, a rider, a conversation) gets **404**. Every change is audit-logged (`core.AuditLog`). Lists are
paginated (`page`, `page_size` ≤ 100) and searched on the server; the browser never downloads whole tables.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/admin/session/` | staff | `user, is_admin, sections[]` (what the menu shows), `stores[]` (the ones this person works with), `can{manage_catalog, manage_stores, manage_offers, manage_customers, manage_riders, adjust_stock, handle_orders, handle_returns}` |
| GET | `/api/admin/summary/` | staff | Live dashboard numbers, `?store=`. `orders{total, today, pending, processing, on_the_way, delivered, cancelled, delivery_failed, by_status}`, `revenue{total, today, this_month, refunded_total}`, `returns{total, open}`, `refunds{pending, pending_amount, failed, processed, processed_amount}`, `inventory{low_stock, out_of_stock}`, `delivery{partners, partners_online, partners_available, waiting_for_rider, cash_with_riders}`, `stores{active, accepting_orders, warehouses}`, `customers` / `products` (administrators, shop-wide; `null` for managers), `trend[]` (14 days), `attention[{code, label, count, link}]` |
| GET | `/api/admin/analytics/` | staff | `?from=&to=` (YYYY-MM-DD, ≤ 366 days, default last 30), `?group_by=day\|week\|month` (default by length), `?store=`. `period, totals{orders, paid_orders, revenue, refunded, net_revenue, average_order_value, delivered, cancelled, cancellation_rate, payment_methods}, series[]` (per period: orders, paid_orders, revenue, refunded, net_revenue, average_order_value, cancelled, delivered), `category_sales[]`, `top_products[]`, `low_performing_products[]`, `cancellations{count, rate, value, reasons}`, `returns{…, reasons}`, `refunds{…}`, `delivery{all, fast, standard: {delivered, with_estimate, on_time, on_time_rate, average_promised_minutes, average_actual_minutes}, first_attempt_rate, failed_attempts, failure_reasons, delivered_by_partners}`. 400 `invalid_date`, `range_too_long` |
| GET | `/api/admin/orders/` | staff | `?q=` (order number, customer name/email/phone, product name, SKU), `?status=` (one or more statuses, or a group `open`, `preparing`, `on_the_way`, `closed`), `payment_status`, `payment_method`, `delivery_type`, `store`, `customer`, `from`, `to`, `has_return`, `ordering`. Rows add `customer{id, name, email, phone, is_active}`, `store_name, item_count, item_names, shipments[{id, sequence, store_name, status, rider}], open_return, refund_status` |
| GET | `/api/admin/orders/{order_number}/` | staff | The customer's order detail plus `customer`, `staff_shipments[]` (the staff shipment rows of Phase 10), `allowed_actions[{status, label}]` (status changes possible now, as the state machine and the delivery rules stand; empty while a rider is in charge) and `can_manage`. Status changes go through `POST /api/orders/{n}/transition/`. The delivery code is never included |
| GET/POST | `/api/admin/products/` | staff read · admin write | `?q=` (name, product or variant SKU), `category` (or subcategory), `brand`, `state=live\|draft\|inactive\|deleted\|all` (default: not deleted), `featured`, `stock=in\|out`, `ordering`. Create with the Phase 4 write body (`variants[]` with `sku, name, mrp, price, is_default, is_active`; `specifications[]`); price ≤ MRP and SKU uniqueness are checked by the catalogue service (400 / 409 `duplicate_sku`) |
| GET/PATCH/DELETE | `/api/admin/products/{id}/` | staff read · admin write | Detail with `variants[]` (+ `stock_available`, `stock_reserved` across stores), `specifications[]`, `images[]`, `state`. PATCH is partial (publish/unpublish = `is_published`; variants are upserted by `id`). DELETE is a **soft delete** (409 `product_deleted` on later changes) |
| POST | `/api/admin/products/{id}/restore/` | admin | Brings a deleted product back, unpublished |
| POST | `/api/admin/products/{id}/images/` | admin | multipart `image` (JPG/PNG/WebP ≤ 5 MB), `alt_text?`, `is_primary?`, `variant?`; at most 12 pictures; the first one becomes primary |
| PATCH/DELETE | `/api/admin/products/{id}/images/{image_id}/` | admin | `{alt_text?, sort_order?, is_primary?}`; deleting the primary picture promotes the next one |
| GET | `/api/admin/variants/?q=` | staff | Up to 20 active variants by product name, variant name or SKU (for stock records, offers) |
| GET/POST, GET/PATCH/DELETE | `/api/admin/categories/`, `…/{id}/` | staff read · admin write | Tree with subcategories incl. inactive ones and `product_count`; `?flat=true` for one list; `?q=`. Two levels only (400). Delete refused while it has products or subcategories (409) |
| GET/POST, GET/PATCH/DELETE | `/api/admin/brands/`, `…/{id}/` | staff read · admin write | `?q=`, `?is_active=`; `product_count`. Delete refused while it has products (409 `brand_has_products`) |
| GET/POST, GET/PATCH/DELETE | `/api/admin/stores/`, `…/{id}/` | staff read (own) · admin write · manager PATCH of own store | `?kind=store\|dark_store\|warehouse\|fulfilment`, `?q=`, `?is_active=`. Rows: `kind_label, zone_count, open_orders, has_location, can_edit (all\|operations\|none)`. Detail adds address, `latitude/longitude`, `opening_hours` (`{"mon": ["09:00","21:00"], "sun": null}`, `{}` = always open; validated), `prep_minutes_per_item`, `managers[]` (+ `manager_ids` to set them), `zones[]`, `inventory{stock_records, units_available, units_reserved, low_stock, out_of_stock}`, `riders{partners, online, own_riders}`. A manager may change only `opening_hours, avg_prep_minutes, prep_minutes_per_item, own_riders, accepts_orders, phone` (403 otherwise). DELETE soft-deletes; 409 `store_has_open_orders`, `store_has_stock` |
| GET/POST, PATCH/DELETE | `/api/admin/zones/`, `…/{id}/` | staff read (own stores) · admin write | Delivery zones: `store, name, radius_km, postal_codes` (6-digit PIN codes, validated), `pin_codes[]`, `polygon` (≥ 3 `[lat, lng]` points), `fast_delivery_enabled, fast_delivery_max_minutes, delivery_fee_override, free_delivery_min_order, effective_fee, effective_free_from, is_active`. Warehouses can't have zones |
| GET/POST, PATCH/DELETE | `/api/admin/pincodes/`, `…/{id}/` | staff read · admin write | PIN code centre points (`?q=`) |
| GET/POST, GET/PATCH/DELETE | `/api/admin/offers/`, `/api/admin/coupons/`, `…/{id}/` | **admin only** | The discount **rules** of Phase 6; the checkout calculates the money (`orders/pricing.py`), never the dashboard. Fields as in `offers.models` plus `products[]`/`categories[]` (ids), `product_details[]`, `category_details[]`, `state=live\|scheduled\|expired\|inactive` (also a list filter), `summary` (the rule in words). Coupons add `remaining_uses`; `used_count` is read-only; a code is stored upper-case and must be unique. Validation: percent ≤ 100, end after start, cap only on percentages, `usage_limit` ≥ `used_count`. A used coupon can't be deleted (409 `coupon_in_use`): switch it off |
| GET | `/api/admin/customers/`, `…/{id}/` | **admin only** | `?q=` (name, email, phone), `?role=` (default `customer`; `all`), `is_active`, `has_orders`, `ordering=-date_joined\|date_joined\|-total_spend\|-order_count\|-last_order_at`. Rows: contact, `order_count` (not cancelled), `total_spend` (paid orders), `last_order_at`. Detail adds `deactivated_at, cancelled_orders, returns, addresses[]` (area/city/PIN), `managed_stores[]`, `recent_orders[]`. Never contains password hashes or tokens. Changes go through `PATCH /api/admin/users/{id}/` (`is_active`, `role`) |
| GET, GET/PATCH | `/api/admin/riders/`, `…/{partner_id}/` | staff read (own stores) · admin PATCH | `?q=`, `?status=offline\|available\|busy\|online`, `?store=`, `?is_verified=`, `?is_active=`. Rows: contact, vehicle, `home_store(_name), status, is_verified, is_active, active_assignments, capacity, can_take_jobs, cash_in_hand, delivered, delivered_today, failed, earnings_today, earnings_7_days, earnings_total`. PATCH `{is_verified?, is_active?, max_active_assignments? (1–10), home_store?, vehicle_type?, vehicle_number?}`; switching a rider off with a job in hand → 409 `active_delivery` |
| GET | `/api/admin/jobs/` | staff (own stores) | Every rider job: `?status=` (a status, or `active`, `completed`, `failed`), `?kind=delivery\|return_pickup`, `?partner=`, `?store=`, `?q=` (order number, rider). Rows: the Phase 10 assignment fields plus `order_number, order_status, shipment_id, store_name, return_number, distance_km` |
| GET, GET | `/api/admin/support/`, `…/{id}/` | staff | Conversations; managers see those about orders of their stores. `?status=` (a status or `active`), `?q=` (subject, customer name/email/phone, order number), `?mine=true`, `?store=`. Rows: `customer{id, name, email, phone}`, `order_number, store_name, assigned_to(_name), message_count, last_message, waiting_for_reply`; detail adds `messages[{sender_type, sender_name, body, created_at}]` |
| POST | `/api/admin/support/{id}/reply/` | staff | `{body}` → 201. Posts an agent message, sets `waiting_customer`, assigns the conversation to the sender if nobody has it |
| PATCH | `/api/admin/support/{id}/` | staff | `{status?, assign_to_me?}` |
| GET | `/api/admin/search/index/` | **admin only** | Phase 13. `{embedder{kind, key, available, dimensions, model?, loaded?}, search_backend, products, indexed, missing, stale, other_embedder, last_updated, ready}` |
| POST | `/api/admin/search/index/rebuild/` | **admin only** | `{force?: false}`. Embeds products whose text changed (all with `force`), removes rows of deleted products. → `{result{embedded, unchanged, removed, failed[]}, status}`; audit-logged. 503 `semantic_unavailable` when no embedder is available (keyword search keeps working). Runs inside the request: for a large catalogue with a local model use `manage.py rebuild_search_index` |
| POST | `/api/admin/search/index/products/{id}/` | **admin only** | Re-embed one product → `{status}`; 404 unknown product; 503 `semantic_unavailable` |
| GET | `/api/admin/search/explain/?q=` | **admin only** | The ranking behind a query: `{mode, embedder, terms, related_terms, sources, matched, results[{product_id, name, keyword, related, semantic, cosine, final, reason}]}`; 400 without `q` |

Also extended for the dashboard: `GET /api/inventory/` takes `?q=` (SKU, product, variant, store) and `?stock=out\|low\|ok`
and rows carry `store_name`; `GET /api/returns/` takes `?q=` and `?store=` and `?status=open` (requested + approved);
`GET /api/payments/refunds/` takes `?q=` and `?store=` and rows carry `customer_name`, `store_name`.

## AI hardware assistant (Phase 12)
Customers only (JWT). Each customer sees and changes only their own conversations (another customer's id gives 404).
Asking is limited by the `ai` throttle (`THROTTLE_AI`, default 30/min). Products in answers are read from the database
when the answer is built and again when it is shown, so a price or stock change is never stale and no product can be invented.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/ai/assistant/` | public | `{ai_mode: basic\|llm, provider, model, languages, suggested_prompts, greeting, max_products}`. Never exposes keys or URLs |
| GET, POST | `/api/ai/conversations/` | customer | List (with `message_count`) / start a conversation. POST `{message?, language?: en\|hi\|hinglish}`: with `message` the first answer is included |
| GET, DELETE | `/api/ai/conversations/{id}/` | owner | Detail with messages / delete the conversation |
| POST | `/api/ai/conversations/{id}/messages/` | owner | `{message (max length enforced), language?}` → 201 `{conversation_id, title, user_message, assistant_message}` |
| POST | `/api/ai/conversations/{id}/clear/` | owner | Removes the messages, keeps the conversation |

Assistant message fields: `content`, `intent` (PRODUCT_SEARCH, PROJECT_HELP, REPAIR_HELP, COMPATIBILITY, QUANTITY, BUDGET,
GENERAL_HARDWARE_QUESTION), `products[]` (catalog product cards with live price, discount, stock and delivery data, plus the
`reason` and `variant_id` chosen), `questions[]` (follow-ups), `actions[]` (e.g. add these items to the cart), `knowledge[]`
(general hardware facts, kept apart from catalog facts), `safety[]`, `estimate` (labelled as an estimate), `ai_mode`, `notice`
("AI is temporarily unavailable. You can search products normally." when a configured model failed).
Adding to the cart uses the normal cart API (`POST /api/cart/items/`); the assistant has no endpoint that touches prices,
inventory or orders.

## Photo search (Phase 14)
Find a product from a photo. Anyone may search (limited by the `image_search` throttle, `THROTTLE_IMAGE_SEARCH`,
default 10/min per user or IP); signed-in customers also get a history, which only they can see or delete (another
customer's id gives 404). The photo is validated, cleaned (EXIF/GPS removed) and analysed, then **discarded**. The vision
model only names the item; products always come from the catalogue search over published products, and every card is
built from live database rows (price, stock, delivery) when it is shown.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/ai/image-search/` | public, not throttled | `{enabled, available, provider, model, calibrated, max_bytes, max_megabytes, accepted_types}`. Never exposes keys or URLs |
| POST | `/api/ai/image-search/` | public, throttled | multipart `image` (JPEG/PNG/WebP, ≤ `IMAGE_SEARCH_MAX_BYTES`, default 8 MB). → 200 result (below). Errors: 400 `image_required`, `image_empty`, `image_invalid` (not a readable picture: renamed PDF, truncated file…), `image_unsupported` (GIF, BMP, HEIC…), `image_too_small` (< 32 px), `image_too_many_pixels` (> 40 MP); 413 `image_too_large` (also refused from `Content-Length` before the upload is parsed); 429 throttled |
| GET | `/api/ai/image-searches/` | customer | Own photo searches, newest first: `{id, title, status, label, percent, product_count, created_at}` |
| GET, DELETE | `/api/ai/image-searches/{id}/` | owner | The result as answered (products rebuilt from the live catalogue) / delete it |
| POST | `/api/ai/image-searches/clear/` | customer | Delete all own photo searches (204) |

Result: `id` (saved search, `null` for visitors), `status` and `status_text`:

| `status` | Meaning | Products |
|---|---|---|
| `identified` | The item is named with enough confidence (CLIP probability ≥ 50 %, or a vision model's own estimate, capped at 80 %) | Products named after the item (`reason` "Matches “claw hammer”"), products only tagged/categorised with it ("Related to …"), up to 2 per likely alternative |
| `uncertain` | Not sure; up to three possibilities | "Possible match: pipe wrench (29%)" for each possibility |
| `not_hardware` | A person, pet, screenshot, … (or the vision model says it isn't hardware) | none |
| `no_match` | Identified, but the shop doesn't sell it | none; `search_query` for a word search |
| `unavailable` | Photo search off, model missing/loading/failing | none; the page offers a word search |

Also: `explanation` (customer wording), `identification {label, confidence, percent, level: high|medium|low, calibrated,
description}`, `alternatives[{label, confidence, percent, search}]`, `search_query`, `notice` (shown for vision-model
answers: "can be wrong"), `ai {mode, provider, model, calibrated}`, `image {format, width, height, bytes, fingerprint}`,
`products[]` (catalogue cards like the assistant's: `variant_id`, `reason`, `match_label`, `match_confidence`).
Adding to the cart is the normal `POST /api/cart/items/` with the card's `variant_id`.

## Planned 🔜
- **AI** more endpoints in Phases 18–22 (voice, projects, calculators, compatibility, smart cart). **Notifications/support channels** (Phase 23).
