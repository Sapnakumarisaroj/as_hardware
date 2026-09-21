# Database Design (portable: PostgreSQL ⇄ MySQL/MariaDB ⇄ SQLite)

Conventions:
- Primary keys: `BigAutoField` internally. Public-facing identifiers use a `public_id UUID` (orders, payments) or a human-readable number (`order_number`), so sequential IDs are never exposed.
- Every table gets `created_at` / `updated_at` (from `core.TimeStampedModel`).
- Soft delete (`is_deleted`, `deleted_at`, via `core.SoftDeleteModel`) applies to catalog entities, addresses, coupons, stores and reviews, which orders reference historically. Orders, payments and history tables are **never** deleted.
- Money is stored as `DECIMAL(12,2)` in INR. Order lines snapshot price, name and SKU at purchase time.
- **Portability rules** (the production DB depends on the hosting plan, see DEPLOYMENT.md §0): no `ArrayField`/`HStoreField`/`django.contrib.postgres` in models, so lists are stored as `JSONField`; no partial/conditional unique indexes (MySQL lacks them), so they are enforced in services under `select_for_update`; `CheckConstraint` is fine (MySQL 8.0.16+ / MariaDB 10.2+); and PostgreSQL-only speedups (`pg_trgm` GIN, tsvector) are added by **conditional migrations** that no-op on other vendors.
- Minimum versions for Django 5.2: PostgreSQL 14+, MySQL 8.0.11+, MariaDB 10.5+.
- JSON columns below are `JSONField` (jsonb on PostgreSQL, JSON on MySQL).

Status: tables marked ✅ exist in the database. Everything else is the planned design, built in the phase listed.

## Core (Phase 1) ✅
| Table | Key columns | Notes |
|---|---|---|
| `core_auditlog` ✅ | actor_id FK user (nullable), action, target_type, target_id, changes JSON, ip, request_id, created_at | index (target_type, target_id), index created_at |

## Accounts (Phase 2–3)
| Table | Key columns | Constraints / indexes |
|---|---|---|
| `accounts_user` ✅ | email (unique + case-insensitive unique on lower(email)), phone (unique, nullable), full_name, role enum(customer, store_staff, delivery_partner, admin), is_active, is_staff, email_verified, phone_verified | unique lower(email) |
| `accounts_customerprofile` | user 1:1, marketing_opt_in, personalization_opt_in, preferred_language | |
| `accounts_address` | user FK, label, name, phone, line1, line2, landmark, city, state, pincode, lat, lng, is_default, soft delete | single default per user enforced in `set_default_address()` service (locks user's addresses) |
| `accounts_passwordresettoken` | user FK, token_hash, expires_at, used_at | index token_hash |

## Catalog (Phase 4)
| Table | Key columns | Constraints / indexes |
|---|---|---|
| `catalog_category` | name, slug, parent FK self (nullable → subcategory tree), description, image, sort_order, is_active, soft delete | unique (parent, slug); index parent |
| `catalog_brand` | name, slug unique, logo | |
| `catalog_product` | name, slug unique, category FK, brand FK, description, short_description, tags JSON, search_text (denormalised lowercase name+brand+tags+specs for portable search), is_active, avg_rating, rating_count, soft delete | index (category, is_active); PostgreSQL-only: GIN trigram on name + FTS index via conditional migration |
| `catalog_productvariant` | product FK, sku unique, name, mrp, price, unit (piece/m/kg/L/box), attributes JSON, weight_grams, is_active | CHECK price <= mrp, price > 0 |
| `catalog_productimage` | product FK, variant FK nullable, image, alt_text, sort_order, is_primary | |
| `catalog_productspecification` | product FK, key, value, unit, normalized_value decimal nullable | unique (product, key); index (key, normalized_value) for spec search |
| `catalog_searchterm` | term unique, frequency | vocabulary for typo correction on MySQL/SQLite |

A **SubCategory** is a `Category` with a parent. This supports unlimited nesting, and admins create categories dynamically.

## Locations & Inventory (Phase 7, 9)
| Table | Key columns | Constraints |
|---|---|---|
| `locations_store` | name, code unique, type enum(store, warehouse, dark_store), address fields, lat, lng, phone, opening_hours JSON, avg_prep_minutes, is_active, soft delete | |
| `locations_deliveryzone` | store FK, name, radius_km, polygon JSON (optional, [[lat,lng],…], point-in-polygon in Python), max_fast_delivery_km, is_active | |
| `locations_geocodecache` | query_hash unique, lat, lng, display_name, provider | Nominatim results cached to respect its usage policy |
| `inventory_inventory` | store FK, variant FK, quantity, reserved, low_stock_threshold | unique (store, variant); CHECK 0 <= reserved <= quantity |
| `inventory_stockmovement` | inventory FK, change (+/-), reason enum(purchase, sale, reservation, release, return, adjustment, transfer), reference_type, reference_id, actor FK, note | index (inventory, created_at) |

## Shopping & Promotions (Phase 6)
| Table | Key columns | Constraints |
|---|---|---|
| `shopping_cart` | user 1:1 (or session_key for guests), coupon FK nullable | |
| `shopping_cartitem` | cart FK, variant FK, quantity | unique (cart, variant); CHECK quantity > 0 |
| `shopping_wishlist` / `shopping_wishlistitem` | user 1:1 / wishlist FK, product FK | unique (wishlist, product) |
| `shopping_recentlyviewed` | user FK, product FK, viewed_at | unique (user, product) |
| `promotions_coupon` | code unique (upper), discount_type enum(percent, fixed), value, max_discount, min_order_value, valid_from, valid_to, usage_limit, per_user_limit, applies_to enum(all, category, product), is_active | |
| `promotions_coupon_categories` / `_products` | M2M | |
| `promotions_couponredemption` | coupon FK, user FK, order FK, discount_amount | unique (coupon, order) |
| `promotions_offer` | title, discount_type, value, target (product/category), starts_at, ends_at, priority, is_active | |

## Orders & Payments (Phase 7–8)
| Table | Key columns | Constraints |
|---|---|---|
| `orders_order` | public_id UUID, order_number unique, user FK, store FK, address snapshot JSON, status, payment_method enum(razorpay, cod), subtotal, discount_total, delivery_fee, tax_total, grand_total, coupon FK, eta_minutes, promised_at, delivery_otp_hash, cancelled_reason | index (user, created_at), index status |
| `orders_orderitem` | order FK, variant FK (PROTECT), product_name, sku, unit_price, mrp, quantity, line_total | |
| `orders_orderstatushistory` | order FK, from_status, to_status, actor FK, note, created_at | index (order, created_at) |
| `orders_returnrequest` | order FK, items JSON, reason, status, resolution | |
| `payments_payment` | public_id, order FK, method, gateway, gateway_order_id unique, gateway_payment_id unique nullable, amount, currency, status enum(created, authorized, captured, failed, refunded, partially_refunded), raw_response JSON | |
| `payments_refund` | payment FK, gateway_refund_id unique, amount, status, reason | |
| `payments_webhookevent` | provider, event_id unique, payload JSON, processed_at | idempotency |

## Delivery (Phase 9–10)
| Table | Key columns |
|---|---|
| `delivery_deliverypartner` | user 1:1, vehicle_type, vehicle_number, is_available, current_lat/lng, last_seen_at, home_store FK |
| `delivery_deliveryassignment` | order 1:1 (active), partner FK, status, assigned_at, picked_up_at, delivered_at, proof_image, otp_verified, earning_amount |
| `delivery_deliverystatushistory` | assignment FK, from_status, to_status, lat, lng, created_at |

## Reviews, Notifications, Support
| Table | Key columns | Constraints |
|---|---|---|
| `reviews_review` | product FK, user FK, order_item FK (verified purchase), rating 1–5, title, body, is_approved, soft delete | unique (user, product); CHECK rating between 1 and 5 |
| `notifications_notification` | user FK, channel, template, title, body, data JSON, status, read_at, sent_at, provider_message_id | index (user, read_at) |
| `support_supportconversation` | user FK, channel enum(whatsapp, call, in_app), order FK nullable, status, assigned_to FK |
| `support_supportmessage` | conversation FK, sender_type, body, attachments JSON |

## AI (Phase 12–19)
| Table | Key columns |
|---|---|
| `ai_aiconversation` | user FK nullable, kind enum(assistant, voice, image, project, business), language, metadata |
| `ai_aimessage` | conversation FK, role, content, tool_calls JSON, product_refs JSON, tokens_in/out, provider, model |
| `ai_project` | user FK, project_type, inputs JSON, status |
| `ai_projectitem` | project FK, variant FK, quantity, is_optional, rationale, is_estimate |
| `ai_bundle` / `ai_bundleitem` | AI-generated or admin bundles; status enum(draft, approved, rejected) |
| `ai_recommendation` | user FK, variant FK, source, score, reason, shown_at, clicked_at |
| `ai_searchhistory` | user FK nullable, query, normalized_query, filters JSON, results_count, source enum(text, voice, image) |
| `ai_productembedding` | product 1:1, embedding JSON (float list), dims, model, content_hash, updated_at (in-Python cosine similarity; pgvector optional only on PostgreSQL) |

## Transactions
- Checkout (`orders.services.place_order`): one `atomic()` block that locks inventory, reserves stock, creates the order, items, status history and coupon redemption, and creates the payment. Any failure rolls back everything.
- Payment capture and webhook: `atomic()` with `select_for_update` on Payment, with idempotency enforced by the unique `event_id`.
- Status transitions: `select_for_update` on Order, validate the transition, update the status, insert the history row.

## Infrastructure tables (hosting-friendly, no Redis/Celery)
| Table | Purpose |
|---|---|
| `core_job` (Phase 8/20) | DB job queue: name, payload JSON, status, attempts, run_after, locked_at, last_error; drained by cron `run_jobs` |
| `django_cache` | DB cache for throttling/rate limits in production (`manage.py createcachetable`) |
