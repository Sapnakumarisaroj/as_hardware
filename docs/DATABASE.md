# Database Design

Portable across **SQLite (local, tested)**, **PostgreSQL** and **MySQL/MariaDB** (hosting). The database vendor is chosen only by `DATABASE_URL`.

> **Tested status:** migrations and all tests run on **SQLite only**. PostgreSQL and MySQL/MariaDB compatibility is
> by design (see the portability rules below) but has **not yet been executed** against those servers.

Legend: ✅ implemented (Phase 1–2) · 🔜 planned (phase)

## Conventions
- Primary keys are `BigAutoField`. Public identifiers are `order_number` (e.g. `OD260921K7M2QX`) and `public_id` UUIDs for payments; sequential IDs are not exposed where it matters.
- `created_at` / `updated_at` come from `core.TimeStampedModel`.
- Soft delete (`is_deleted`, `deleted_at`, `core.SoftDeleteModel`) applies to Category, Brand, Product, Store and Address. The default manager hides deleted rows; `all_objects` includes them. Orders, payments, stock movements and history tables are never deleted.
- **Money** is `DECIMAL(12,2)` in INR and Python `Decimal` everywhere (`core.money.q` for half-up rounding). There is no float.
- **Prices are GST-inclusive** (Indian retail practice). `tax_total` is the GST contained in the amount payable.
- Order lines and the delivery address are **snapshots** copied at purchase time.

## Portability rules (so Hostinger / shared MySQL works)
| Rule | Why |
|---|---|
| No `ArrayField`, `HStoreField` or `django.contrib.postgres` | PostgreSQL-only. Lists/maps use `JSONField` |
| No partial/conditional unique indexes | MySQL/MariaDB lack them. "One default address" and "one active delivery assignment" are enforced in services under `select_for_update` |
| No functional indexes (e.g. `Lower(email)`) | MariaDB lacks them. Emails, SKUs, store codes and coupon codes are **normalised on save** (lower/upper case) and use plain unique indexes |
| `CheckConstraint`s only on simple comparisons | Supported on PostgreSQL, SQLite, MySQL 8.0.16+ and MariaDB 10.2+. Services validate the same rules first |
| Reads use portable `Subquery`/`Sum`/`Coalesce` | No raw SQL |
| One-to-one guarantees (cart, wishlist, profile) use `OneToOneField` | Portable unique constraint |
| Unique `CharField`s ≤ 255 chars | Within the utf8mb4 index-length limit on MySQL 8 |
| `select_for_update` for stock/orders/coupons | Row locks on PostgreSQL/InnoDB; SQLite serialises writes (fine locally) |

Minimum versions for Django 5.2: PostgreSQL 14+, MySQL 8.0.11+, MariaDB 10.5+.

## Entity overview

```
User ─1:1─ CustomerProfile          Category (self-FK: parent → subcategories)
  │  └─< Address                       └─< Product >─ Brand
  ├─1:1─ Cart ─< CartItem >─┐              ├─< ProductVariant (SKU, MRP, price) ─< Inventory >─ Store/Warehouse
  ├─1:1─ Wishlist ─< WishlistItem          ├─< ProductSpecification (name/value/unit)     └─< StockMovement
  ├─< Order ─< OrderItem (snapshot)         └─< ProductImage
  │     ├─< OrderStatusHistory
  │     ├─< ReturnRequest ─< ReturnItem >─ OrderItem      (ReturnRequest ─1:1─ Refund)
  │     ├─< Payment ─< Refund               Coupon ─< CouponRedemption >─ Order
  │     └─< DeliveryAssignment ─< DeliveryStatusHistory >── DeliveryPartner ─1:1─ User
  ├─< Review >─ Product                     Store ─< DeliveryZone
  ├─< Notification · SupportConversation ─< SupportMessage
  └─< AIConversation ─< AIMessage · Project ─< ProjectItem
```

## accounts ✅
| Table | Key columns | Constraints / indexes |
|---|---|---|
| `accounts_user` | email (unique, stored lower-case), phone (unique, nullable), full_name, role (customer/store_staff/delivery_partner/admin), is_active, is_staff, email_verified, phone_verified | unique email, unique phone, index role |
| `accounts_customerprofile` | user 1:1, preferred_language (en/hi/hi-latn), marketing_opt_in, whatsapp_opt_in, personalization_opt_in | auto-created on signup (signal) |
| `accounts_address` | user FK, name, phone (10-digit, normalised), address_line1/2, area, landmark, city, state, postal_code (6-digit PIN), country, latitude/longitude DECIMAL(9,6), address_type (home/work/site/other), is_default, soft delete | index (user, is_deleted, is_default), index postal_code. One default per user enforced by `accounts.services` |

## catalog ✅
| Table | Key columns | Constraints / indexes |
|---|---|---|
| `catalog_category` | name, slug (unique), parent FK self (null = top level), description, image, sort_order, is_active, soft delete | index (parent, is_active, sort_order). Max 2 levels (validated). Proxies: `TopCategory`, `SubCategory` |
| `catalog_brand` | name (unique), slug (unique), logo, description, is_active, soft delete | |
| `catalog_product` | name, slug (unique), sku (unique, upper), brand FK, category FK (top level), subcategory FK (child of category), short_description, description, tags JSON list, unit, gst_rate (0–40 %), hsn_code, max_order_quantity, is_active, is_published, is_featured, is_returnable, rating_avg, rating_count, soft delete | indexes (category/subcategory, is_active, is_published), (brand, is_active), (is_featured, is_published) |
| `catalog_productvariant` | product FK, sku (unique, upper), name, attributes JSON, mrp, price, weight_grams, length/width/height_mm, is_default, is_active, sort_order | CHECK price > 0, CHECK price ≤ mrp; index (product, is_active) |
| `catalog_productimage` | product FK, variant FK (nullable), image (jpg/png/webp ≤ 5 MB, random filename), alt_text, sort_order, is_primary | |
| `catalog_productspecification` | product FK, name, key (slug of name), value, unit, numeric_value DECIMAL (auto-parsed), sort_order | unique (product, key); index (key, numeric_value), (key, value) |
| `catalog_recentsearch` (Phase 4) | user FK, query, normalized (lower-case), searched_at | unique (user, normalized); max 10 rows per user (older ones pruned on write); cascade-deleted with the user |

**Filters and search (Phase 4)** read these tables without new columns. Listing price/MRP/discount, total and
fast-delivery stock, units sold and variant count are annotated with portable correlated subqueries (one SQL query per
page). Specification filters use `ProductSpecification.key`/`value`, so new filterable attributes need no migration: add
the specification in the admin and it appears as a filter once enough products in a listing share it.

**Why variants?** Every purchasable unit (SKU + MRP + price + weight) is a `ProductVariant`. A simple product has one
variant; a wire in four gauges has four. Inventory, cart and order lines always point at a variant, so there is one code
path. Product-level MRP/price/discount/stock state are **derived** (cheapest active variant; total available stock) rather
than duplicated, so they can never disagree. **Stock state** is computed: `in_stock` / `low_stock` (≤ 5) / `out_of_stock`.

## stores ✅
| Table | Key columns | Notes |
|---|---|---|
| `stores_store` | name, code (unique, upper), kind (store / dark_store / warehouse), phone, email, address fields, postal_code, latitude/longitude, opening_hours JSON, avg_prep_minutes, is_active, accepts_orders, soft delete | index (kind, is_active, accepts_orders). `Warehouse` = proxy (kind=warehouse). Stores and dark stores fulfil orders; warehouses do not |

## inventory ✅
| Table | Key columns | Constraints |
|---|---|---|
| `inventory_inventory` | store FK, variant FK, available_quantity, reserved_quantity, low_stock_threshold, is_active | unique (store, variant); **CHECK available ≥ 0, reserved ≥ 0** |
| `inventory_stockmovement` | inventory FK, movement_type, quantity, available_after, reserved_after, reason, reference_type, reference_id, created_by, created_at | append-only ledger; index (inventory, created_at), (reference_type, reference_id) |

Movement effects (only via `inventory.services.apply_movement`, which locks the row and runs in a transaction):

| Type | available | reserved | When |
|---|---|---|---|
| purchase | +n | | stock received |
| reservation | −n | +n | order placed |
| release | +n | −n | order cancelled before pickup |
| sale | | −n | order picked up |
| return | +n | | returned item restocked |
| adjustment | ±n (reason required) | | stock count correction |

## offers ✅
| Table | Key columns | Constraints |
|---|---|---|
| `offers_coupon` | code (unique, upper), description, discount_type (percent/fixed), value, max_discount_amount, min_order_value, starts_at, ends_at, usage_limit, per_customer_limit, used_count, is_active, show_in_checkout (Phase 6, default off), M2M products, M2M categories | CHECK percent ≤ 100; index (is_active, starts_at, ends_at) |
| `offers_couponredemption` | coupon FK, user FK, order 1:1, discount_amount (**coupon portion only**) | index (coupon, user) |
| `offers_offer` | name, description, discount_type, value, max_discount_amount, min_order_value, starts_at, ends_at, priority, is_active, M2M products/categories | CHECK percent ≤ 100; index (is_active, starts_at, ends_at). Applied automatically by `offers.engine` (Phase 6); no usage counters (offers are unlimited while live) |

## carts ✅
| Table | Key columns | Constraints |
|---|---|---|
| `carts_cart` | user 1:1 | one cart per customer |
| `carts_cartitem` | cart FK, variant FK, quantity, price_at_add (informational) | unique (cart, variant); CHECK quantity ≥ 1 |
| `carts_wishlist` | user 1:1 | |
| `carts_wishlistitem` | wishlist FK, product FK | unique (wishlist, product) |

## orders ✅
| Table | Key columns | Constraints / indexes |
|---|---|---|
| `orders_order` | public_id UUID, order_number (unique), user FK, store FK, address_snapshot JSON, status (fulfilment), payment_method (cod/online), payment_status, subtotal, mrp_total, discount_total, delivery_fee, tax_total, grand_total, coupon FK, coupon_code, customer_note, estimated_delivery_at, eta_minutes, cancellation_reason, cancelled_at, delivered_at, idempotency_key (Phase 5, nullable), offer_discount + coupon_discount (= discount_total) and applied_offers JSON snapshot (Phase 6) | CHECK grand_total ≥ 0, discount ≥ 0; **unique (user, idempotency_key)**; indexes (user, created_at), (store, status), (status, created_at) |
| `orders_orderitem` | order FK, variant FK (SET NULL), product FK (SET NULL) + snapshot: product_name, variant_name, sku, brand_name, unit, unit_mrp, unit_price, gst_rate, hsn_code, quantity, line_total, offer_discount (Phase 6: this line's share of automatic offers) | CHECK quantity ≥ 1 |
| `orders_orderstatushistory` | order FK, from_status, to_status, changed_by, note, created_at | index (order, created_at) |
| `orders_returnrequest` (Phase 7) | return_number (unique), order FK (PROTECT), user FK, status (requested/approved/rejected/received/cancelled), reason, details, refund_amount (fixed at request time), refund_method (original_payment/manual), refund 1:1 → `payments_refund` (set when received), decision_note, decided_by, decided_at, received_at, restocked, cancelled_at | CHECK refund_amount ≥ 0; indexes (order, status), (status, created_at) |
| `orders_returnitem` (Phase 7) | return_request FK (CASCADE), order_item FK (PROTECT), quantity, refund_amount | CHECK quantity ≥ 1; unique (return_request, order_item) |

Status flow (`orders/state_machine.py`, the single source of truth):

```
pending → confirmed → processing → packed → assigned → picked_up → out_for_delivery → delivered → return_requested → returned
   └──────────┴────────────┴──────────┴─────────┴──→ cancelled            (assigned → packed = unassign; return_requested → delivered = rejected)
```
Customers can cancel while `pending`, `confirmed` or `processing`. Cancelling releases reserved stock, voids uncaptured
payments, records a *pending* `payments_refund` for captured ones (processed by the Phase 8 gateway workflow) and deletes
the coupon redemption (decrementing `used_count`), so the customer can use the coupon again. `picked_up` converts the
reservation into a sale.

**Idempotency key (Phase 5).** `NULL` rather than an empty string when the client sends none: PostgreSQL, MySQL/MariaDB
and SQLite all allow repeated NULLs in a unique index, so no partial index is needed (portability rule above). Migration
`orders 0002_order_idempotency_key` only adds the column and the constraint; existing orders keep `NULL`.

**Discount breakdown (Phase 6).** Migration `orders 0003_order_discount_breakdown` adds `offer_discount`,
`coupon_discount`, `applied_offers` and `orderitem.offer_discount` (all default 0 / empty) and back-fills
`coupon_discount = discount_total` for existing orders, since the coupon was the only discount before Phase 6
(covered by `orders/tests/test_migrations.py`). `offers 0003_coupon_show_in_checkout` adds the opt-in flag (default off,
so no existing coupon becomes visible).

**Returns (Phase 7).** Migration `orders 0004_return_requests` only creates the two new tables (no data changes).
The order row lock serialises requests, so there is never more than one open request per order. Units in
requested, approved or received returns are no longer returnable. A line's returned refunds are computed
cumulatively (`q(paid × returned_so_far / qty)` differences), so they add up exactly to what was paid for the line.
`receive` writes a `return` stock movement (`reference_type="return"`, `reference_id=<return_number>`) when restocking,
and creates the pending `payments_refund`.

## payments ✅
| Table | Key columns | Constraints |
|---|---|---|
| `payments_payment` | public_id, order FK, provider (mock/razorpay/cod), method, amount, currency, status, provider_order_id, provider_payment_id (unique, nullable), failure_reason, metadata JSON (sanitised), captured_at | CHECK amount > 0 |
| `payments_refund` | public_id, payment FK, amount, status, reason, provider_refund_id (unique, nullable), requested_by, processed_at | CHECK amount > 0 |

**No card numbers, CVV, UPI PINs or bank credentials are ever stored.**

## delivery ✅ (foundation)
| Table | Key columns |
|---|---|
| `delivery_deliveryzone` | store FK, name, radius_km, polygon JSON (optional), fast_delivery_enabled, delivery_fee_override, is_active |
| `delivery_deliverypartner` | user 1:1, phone, vehicle_type, vehicle_number, home_store FK, status (offline/available/busy), is_verified, is_active, current lat/lng, last_location_at |
| `delivery_deliveryassignment` | order FK, partner FK, status, assigned/accepted/picked_up/out_for_delivery/delivered timestamps, otp_hash (hash only), otp_verified_at, proof_image, delivery_notes, failure_reason, distance_km, earning_amount |
| `delivery_deliverystatushistory` | assignment FK, from_status, to_status, lat, lng, note, created_at |

## reviews ✅
| Table | Key columns | Constraints |
|---|---|---|
| `reviews_review` | product FK, user FK, order_item FK, rating, title, body, is_verified_purchase, status (pending/approved/rejected), moderated_by, moderated_at, moderation_note | **unique (user, product)**; CHECK 1 ≤ rating ≤ 5. Only customers with a *delivered* order can review (service rule) |

## notifications / support ✅ (foundation)
| Table | Key columns |
|---|---|
| `notifications_notification` | user FK, channel (in_app/email/sms/whatsapp/push), event, title, body, data JSON, status (pending/sent/failed/skipped), provider, provider_message_id, error, sent_at, read_at. Phase 5 writes `order.placed`, `order.confirmed`, `order.cancelled`, `payment.failed` (in-app + email via Django's email backend, only after the order transaction commits) |
| `support_supportconversation` | user FK (nullable), contact_phone, channel, subject, order FK, status, assigned_to, last_message_at |
| `support_supportmessage` | conversation FK, sender_type (customer/agent/bot/system), sender FK, body, attachments JSON, channel_message_id |

## ai ✅ (data only, no AI logic yet)
| Table | Key columns |
|---|---|
| `ai_aiconversation` | user FK (nullable), session_key, kind (assistant/voice/image/project/business), language, title, metadata JSON |
| `ai_aimessage` | conversation FK, role, content, tool_calls JSON, product_refs JSON (catalog IDs actually shown), provider, model, tokens_in/out |
| `ai_project` | user FK, conversation FK, project_type (painting/bathroom_repair/…), title, inputs JSON, safety_notes, status |
| `ai_projectitem` | project FK, variant FK (nullable), label, quantity DECIMAL, unit, is_optional, is_estimate, rationale, sort_order |

## core ✅
| Table | Purpose |
|---|---|
| `core_auditlog` | append-only admin/sensitive action log (actor, action, target, changes JSON, IP, request_id) |

## Planned tables 🔜
`accounts_passwordresettoken` (Phase 3) · `ai_searchhistory`, `ai_recommendation`, `ai_bundle`/`ai_bundleitem` (Phases 13–19) · `ai_productembedding` (JSON vectors, Phase 13) · `payments_webhookevent` (idempotency, Phase 8) · `core_job` (DB job queue for cron, Phase 8/20) · `locations geocode cache` (Phase 9) · `django_cache` (prod DB cache, created by `createcachetable`).

## Transactions
- `orders.services.place_order` runs in one atomic block. It locks the customer's cart row (so concurrent "Place order"
  clicks queue), returns the existing order if the idempotency key was already used, locks the cart lines and coupon,
  validates, recalculates totals (compares them with `expected_total`), picks a store, creates the order, items, stock
  reservations, redemption, status history and payment, then clears the cart. Any failure rolls back everything, and
  notifications are only sent on commit (both tested).
- `payments.services.verify_payment` locks the payment and order rows, so a double submit can't capture twice.
- `orders.services.transition_order` / `cancel_order_by_customer` lock the order, validate against the state machine, apply stock side effects, and write history.
- `orders.returns` (Phase 7): `request_return` locks the order; `cancel/approve/reject/receive_return` lock the return and then the order (always in that order), so concurrent receives restock and refund exactly once.
- `orders.services.reorder` locks the cart row while it merges the order's lines into the cart.
- `inventory.services.apply_movement` locks the inventory row, validates non-negativity and writes the ledger row.
- **SQLite (local/tests)** has no row locks. Settings open every transaction with `BEGIN IMMEDIATE` (`transaction_mode`,
  20 s busy timeout), so concurrent writers wait their turn instead of failing with "database is locked". The
  concurrency tests (`orders/tests/test_concurrency.py`, real threads) prove the invariants on SQLite. PostgreSQL/MySQL
  get the same guarantees from the `select_for_update` row locks above.
- Cart add/update lock the cart row. Address default changes lock the user's addresses.
