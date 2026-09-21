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

## Catalog ✅
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/categories/` | public | Top-level categories with nested `children` (subcategories) |
| GET | `/api/categories/{slug}/` | public | |
| POST/PUT/PATCH/DELETE | `/api/categories/…` | admin | Delete is soft, refused if it has subcategories/products (409) |
| GET | `/api/brands/`, `/api/brands/{slug}/` | public | |
| POST/PUT/PATCH/DELETE | `/api/brands/…` | admin | Soft delete |
| GET | `/api/products/` | public | Filters: `category` (includes subcategories), `subcategory`, `brand` (comma list), `min_price`, `max_price`, `in_stock`, `featured`, `q` (name/SKU/brand keyword). `ordering`: `price`, `-price`, `newest`, `name`, `rating`. Returns price/MRP/discount of the cheapest variant and `stock_status` |
| GET | `/api/products/{slug}/` | public | Variants (with `available_quantity`, `stock_status`), specifications, images, GST, limits |
| POST | `/api/products/` | admin | Product + `variants[]` + `specifications[]` in one request (transactional) |
| PUT/PATCH | `/api/products/{slug}/` | admin | Variants upserted by `id`; specifications replaced |
| DELETE | `/api/products/{slug}/` | admin | Soft delete (past orders keep snapshots) |
| GET | `/api/products/{slug}/reviews/` | public | Approved reviews only, paginated |
| POST | `/api/products/{slug}/reviews/` | customer | `{rating 1–5, title?, body?}`. Requires a delivered purchase; one review per product |

Admins see unpublished products on detail and with `?include_unpublished=true` on list.

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
- **Search** `/api/search/`, suggestions (Phase 4). **AI** `/api/ai/…` (Phases 12–19). **Notifications/support** (Phase 20).
