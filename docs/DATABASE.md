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
| `offers_coupon` | code (unique, upper), description, discount_type (percent/fixed), value, max_discount_amount, min_order_value, starts_at, ends_at, usage_limit, per_customer_limit, used_count, is_active, M2M products, M2M categories | CHECK percent ≤ 100; index (is_active, starts_at, ends_at) |
| `offers_couponredemption` | coupon FK, user FK, order 1:1, discount_amount | index (coupon, user) |
| `offers_offer` | name, discount_type, value, max_discount_amount, min_order_value, starts_at, ends_at, priority, is_active, M2M products/categories | data only; automatic application is planned for Phase 6 |

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
| `orders_order` | public_id UUID, order_number (unique), user FK, store FK, address_snapshot JSON, status (fulfilment), payment_method (cod/online), payment_status, subtotal, mrp_total, discount_total, delivery_fee, tax_total, grand_total, coupon FK, coupon_code, customer_note, estimated_delivery_at, eta_minutes, cancellation_reason, cancelled_at, delivered_at | CHECK grand_total ≥ 0, discount ≥ 0; indexes (user, created_at), (store, status), (status, created_at) |
| `orders_orderitem` | order FK, variant FK (SET NULL), product FK (SET NULL) + snapshot: product_name, variant_name, sku, brand_name, unit, unit_mrp, unit_price, gst_rate, hsn_code, quantity, line_total | CHECK quantity ≥ 1 |
| `orders_orderstatushistory` | order FK, from_status, to_status, changed_by, note, created_at | index (order, created_at) |

Status flow (`orders/state_machine.py`, the single source of truth):

```
pending → confirmed → processing → packed → assigned → picked_up → out_for_delivery → delivered → return_requested → returned
   └──────────┴────────────┴──────────┴─────────┴──→ cancelled            (assigned → packed = unassign; return_requested → delivered = rejected)
```
Customers can cancel while `pending`, `confirmed` or `processing`. Cancelling releases reserved stock; `picked_up` converts the reservation into a sale.

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
| `notifications_notification` | user FK, channel (in_app/email/sms/whatsapp/push), event, title, body, data JSON, status (pending/sent/failed/skipped), provider, provider_message_id, error, sent_at, read_at |
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
`accounts_passwordresettoken` (Phase 3) · `ai_searchhistory`, `ai_recommendation`, `ai_bundle`/`ai_bundleitem` (Phases 13–19) · `ai_productembedding` (JSON vectors, Phase 13) · `payments_webhookevent` (idempotency, Phase 8) · `core_job` (DB job queue for cron, Phase 8/20) · `locations geocode cache` (Phase 9) · `orders_returnrequest` (Phase 7) · `django_cache` (prod DB cache, created by `createcachetable`).

## Transactions
- `orders.services.place_order` runs in one atomic block. It locks the cart lines and coupon, validates, picks a store, creates the order, items, stock reservations, redemption, status history and payment, then clears the cart. Any failure rolls back everything (tested).
- `orders.services.transition_order` / `cancel_order_by_customer` lock the order, validate against the state machine, apply stock side effects, and write history.
- `inventory.services.apply_movement` locks the inventory row, validates non-negativity and writes the ledger row.
- Cart add/update lock the cart row. Address default changes lock the user's addresses.
