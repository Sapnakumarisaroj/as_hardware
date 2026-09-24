# TASKS

Legend: `[x]` done and verified · `[ ]` open · `[~]` partially done / blocked (reason noted)

## Phase 1 — Repository inspection, architecture, setup ✅ (2026-09-21)
- [x] Inspect repository (was empty) and local toolchain (Python 3.11, Docker 29, no Node, so portable Node 24.21 LTS installed to `%LOCALAPPDATA%\tools`)
- [x] Inspect for hosting config: none detectable (see DEPLOYMENT.md §0)
- [x] docs: ARCHITECTURE, DATABASE, API, ROADMAP, DEPLOYMENT
- [x] Backend: Django 5.2 project, split settings (base/dev/test/prod), env-driven config, `.env` lookup (ENV_FILE → backend/.env → repo .env)
- [x] Vendor-portable DB config: PostgreSQL / MySQL (PyMySQL) / SQLite via `DATABASE_URL`
- [x] DRF defaults: JWT auth, IsAuthenticated by default, pagination, throttling scopes, OpenAPI (`/api/schema|docs|redoc/`)
- [x] core app: `TimeStampedModel`, `SoftDeleteModel` (+ managers), `AuditLog` + `record_audit()`, request-ID middleware + log filter, error envelope + `ServiceError`, `/api/health/` (DB check)
- [x] accounts app: custom `User` (email login, roles, lowercase-normalised email), admin
- [x] Prod settings: HSTS/secure cookies, DB cache for throttling, guard that blocks `PAYMENT_PROVIDER=mock`
- [x] Provider selection settings (payments/WhatsApp/SMS/maps/LLM/jobs) with free defaults
- [x] `passenger_wsgi.py` for shared hosting; `requirements/{base,dev,prod,mysql}.txt`
- [x] Frontend: React 19 + TS strict + Vite 8 + Tailwind 4 theme, Router, TanStack Query, Axios client + `ApiError`, layout, home (live API status with loading/error/retry), 404, route error page, `.htaccess`
- [x] Tooling: ruff, pytest; ESLint, Vitest + Testing Library
- [x] `.env.example`, `.gitignore`, Dockerfiles, optional `docker-compose.yml`, README
- [x] Verified: backend 14 tests pass, ruff clean, `check` + `check --deploy` (prod) clean, migrations apply (SQLite); frontend lint/typecheck clean, 7 tests pass, production build OK; live health 200 + CORS OK
- [~] `docker compose up` not run: starting containers was declined during this session. Compose file is optional/local-only
- [~] Not yet tested against PostgreSQL or MySQL servers (needs a local DB server or the hosting DB)
- [x] Git initialised; Phase 1 committed (`272e205`) with `.gitattributes` (LF) and verified that no secrets are staged

## Phase 2 — Database + backend foundation ✅ (2026-09-21)
- [x] 12 new modular apps: catalog, stores, inventory, offers, carts, orders, payments, delivery, reviews, notifications, support, ai (kept Phase 1 `accounts` instead of renaming to `users`, because renaming a migrated custom-user app is risky)
- [x] accounts: `CustomerProfile` (auto-created), `Address` (area, lat/lng, type, default, soft delete) + default-address service
- [x] catalog: Category tree + `TopCategory`/`SubCategory` proxies, Brand, Product (SKU, GST, HSN, flags, soft delete), ProductVariant (SKU/MRP/price/weight/dims; CHECK price ≤ MRP), ProductImage (validated), flexible ProductSpecification (key/value/unit/numeric)
- [x] stores: Store (store/dark store/warehouse) + `Warehouse` proxy
- [x] inventory: Inventory (available/reserved, CHECK ≥ 0), StockMovement ledger; `apply_movement` (locked, transactional; purchase/reservation/release/sale/return/adjustment)
- [x] offers: Coupon (percent/fixed, cap, min order, dates, usage + per-customer limits, product/category scope), CouponRedemption, Offer (data only); coupon validation service
- [x] carts: Cart (1 per user), CartItem (price snapshot, stock-validated), Wishlist(Item)
- [x] orders: Order, OrderItem snapshots, OrderStatusHistory, state machine, shared pricing (GST-inclusive tax, delivery fee), `place_order` (atomic: stock reservation at one store, coupon redemption, payment record), transitions, customer cancel
- [x] payments: Payment, Refund; `integrations/payments` PaymentProvider interface + `MockPaymentProvider` (HMAC-signed, dev only); Razorpay stub raises "not implemented (Phase 8)"
- [x] delivery: DeliveryZone, DeliveryPartner, DeliveryAssignment (OTP hash, proof image), DeliveryStatusHistory (foundation only)
- [x] reviews: Review (unique per user+product, rating CHECK, verified-buyer rule, moderation + rating aggregation)
- [x] notifications / support / ai: Notification, SupportConversation/Message, AIConversation/Message, Project/ProjectItem (data only)
- [x] APIs: categories, brands, products (+ reviews), addresses, cart, coupon preview, wishlist, orders (+ cancel, staff transition), inventory (+ adjust, movements). OpenAPI validates with 0 warnings
- [x] Role permissions (`core/permissions.py`): public read, admin writes, staff inventory/transitions, owner-only data
- [x] Django admin for all models (inline variants/specs/images, stock via ledger only, read-only money records, order status actions through the state machine, review moderation actions)
- [x] `python manage.py seed_demo_data`: idempotent, refuses when DEBUG=False; 35 categories, 6 "(Demo)" brands, 39 products, 47 variants, 3 Pune demo stores, 141 stock records, 2 demo coupons; all SKUs/stores prefixed `DEMO-`
- [x] Portability: no Postgres-only fields, partial or functional indexes; SKU/store/coupon codes normalised so MySQL's case-insensitive collation behaves like PostgreSQL
- [x] Fixed a Phase 1 bug found by live testing: a blank `JWT_SIGNING_KEY` in `.env` gave an empty signing key (regression test added)
- [x] Verified: 85 backend tests pass (94 % line coverage), ruff lint + format clean, `manage.py check` clean, `makemigrations --check` clean, migrations apply on SQLite, live server passes 19 end-to-end HTTP checks, docs/schema/admin return 200, frontend unchanged and still served
- [~] PostgreSQL / MySQL: reviewed for portability, **not executed** (no server available locally)
- [~] Frontend npm checks not re-run in Phase 2 (commands declined; frontend files unchanged since the Phase 1 commit, verified with git)

## Blocked on owner input
- [ ] Hosting details (DEPLOYMENT.md §0 checklist): needed for Phase 24 only
- [ ] Confirm brand name ("BoltRun" placeholder)
- [ ] Choose local DB for dev parity: SQLite (current), Docker PostgreSQL, or local MySQL matching the host

## Phase 3 — Authentication + authorization ✅ (2026-09-22)
- [x] Auth API: register (always `customer`), login, refresh (rotation + blacklist), logout (blacklist), `me`, profile + avatar, self-deactivation; `auth` throttle scope per IP
- [x] Per-account login lockout (`LOGIN_MAX_FAILURES`/`LOGIN_LOCKOUT_SECONDS`, cache-backed, hashed email key); inactive accounts get 403
- [x] Hardened JWT auth: tokens issued before the last password change/reset are rejected (access and refresh); change-password keeps the current session only
- [x] Password reset: emailed single-use link (`FRONTEND_URL`), 1 h expiry, no account enumeration; letter+digit password validator
- [x] Roles: admin-only user management (`/api/admin/users/`: list/filter/detail/patch role, active flag, store assignments); admins cannot demote/deactivate themselves; audit-logged
- [x] Store managers scoped to assigned stores (`Store.managers`) for inventory, movements, orders and transitions
- [x] Delivery partner self-service: `/api/delivery/me/` (availability), `assignments/`, `earnings/`, own data only
- [x] Customer endpoints: support conversations, AI conversations, my reviews
- [x] OpenAPI documents the custom JWT class as Bearer `jwtAuth` (schema extension)
- [x] Tests: `core/tests/test_role_access.py` (role-positive + cross-role/cross-store/cross-partner denials), `accounts/tests/test_auth_flow.py` (register, lockout, rotation, logout, password change/reset)
- [x] Verified: 104 backend tests pass, ruff lint clean, `check` clean, `check --deploy` (prod settings) has no security warnings, `makemigrations --check` clean; fresh SQLite DB migrates from zero + seed idempotent; live server: 22 smoke checks + 52 role checks with real JWT logins for admin, store manager, 2 delivery partners and a customer (temporary dev-only accounts, removed afterwards by rebuilding the dev DB); frontend lint/typecheck clean, 7 tests pass (frontend unchanged)
- [~] 7 Phase 3 files are not `ruff format`-clean (lint is clean); 5 drf-spectacular enum-naming warnings remain (cosmetic)
- [~] Reset emails use the console backend in dev; production needs SMTP settings (`EMAIL_*`)

## Phase 4 — Catalog + customer shopping experience ✅ (2026-09-24)
- [x] Backend: listing annotated in one query (cheapest-variant price/MRP, Decimal discount, total + fast-delivery stock, units sold, variant count); filters `q`, `category` (incl. subcategories), `subcategory`, `brand`, price range, `rating`, `discount`, availability, `fast_delivery`, `featured`, `bestseller`, `exclude`, `spec_<key>`; orderings relevance/price/-price/newest/rating/discount/popular/name with unique tie-breakers
- [x] `/products/facets/`: counts per dimension ignoring its own filter; specification filters shown only when shared by ≥ 40 % of results (drills → chuck size/voltage)
- [x] Pluggable search backend (`CATALOG_SEARCH_BACKEND`), portable keyword engine: name/SKU/brand/category/tags/variant/spec/description, weighted relevance, all-words then any-word fallback (`search.matched`); `/search/suggest/`; per-customer `/search/recent/` (`RecentSearch`, migration `catalog 0002`)
- [x] Categories return product counts and children; subcategory detail includes its parent
- [x] Stock shown as in stock / limited / out of stock; exact quantity only when low ("Only 3 left"); no per-store figures
- [x] Demo product images drawn locally with Pillow by `seed_demo_data` (`--no-images` to skip), clearly marked DEMO
- [x] Django admin: variant `attributes` editable inline; `RecentSearch` view/delete only; admin pages covered by tests
- [x] Frontend: sticky header (logo, location PIN, search with type-ahead/recent searches/clear/loading, "Ask AI · Soon" placeholder, wishlist, cart count, account menu or Login/Register, category mega-nav, mobile drawer menu), footer
- [x] Homepage: hero, categories from API, Today's offers, Best sellers, Featured, Fast delivery, Recently added, "Recommended for you" (from wishlist); empty sections hidden, no fake stats
- [x] Category (`/c/:slug`) / search (`/search`) / all products (`/products`): URL-driven filters, sort, numbered backend pagination, active-filter chips, mobile filter drawer, loading/error/retry/empty states
- [x] Product page (`/p/:slug`): gallery with thumbnails + fallback, variant selector (`?variant=`) switching price/MRP/saving/SKU/stock/delivery/attributes/images, quantity capped by stock and order limit, spec table, description, reviews, related products, sticky mobile add-to-cart, honest delivery text (no fixed 60-minute promise)
- [x] Wishlist and cart wired to existing APIs; logged-out actions saved and completed after login; backend errors ("Only 2 available") shown as toasts
- [x] Basic SEO (titles, meta descriptions, slug URLs) and accessibility (landmarks, labels, combobox search, radio-group variants, focus states, text not colour-only)
- [x] Bugs found by live checks and fixed: discount sort/filter used integer division on SQLite (now float ranking, regression test); recent-search order was wrong when timestamps tied on Windows (re-insert, test was flaky)
- [x] Tests: backend 141 pass (new `test_discovery.py`, `test_admin.py`); frontend 44 pass across 8 files (home/header, product card, category listing/filters/sort/pagination/states, product detail/variants/cart, search, wishlist, cart page)
- [x] Verified: ruff lint clean, `check` clean, `makemigrations --check` clean, migration applied to dev DB; frontend lint/typecheck clean, production build OK; 43 live HTTP checks against the running dev servers (catalog, search, filters, sorting, pagination, detail, wishlist, cart, customer authorization) with a temporary dev customer, deleted afterwards
- [~] Browser testing NOT performed: the connected Chrome could not load `localhost`/`127.0.0.1` (error page for both the Vite and Django servers), so visual/responsive/console checks were done only through component tests
- [x] docs/API.md Phase 3 auth section added in Phase 5

## Phase 5 — Checkout + order experience ✅ (2026-09-24)
- [x] Project moved out of OneDrive to `C:\dev\as_hardware` by the owner; backend venv recreated from `requirements\dev.txt`
- [x] `POST /api/checkout/preview/` (`orders/checkout.py`): server re-prices the cart, validates stock/availability, address, coupon (all existing rules: dates, minimum order, usage + per-customer limits, product/category scope), quotes delivery (availability, fee, free-delivery threshold, fast-delivery store) and lists blocking issues. No ETA is promised (`eta_minutes: null`)
- [x] `place_order` hardened: per-customer cart-row lock, `Idempotency-Key` (unique `(user, idempotency_key)`, migration `orders 0002`), `expected_total` guard → 409 `totals_changed` (stale prices never charged), notifications on commit; still one transaction (stock reservation, snapshots, history, coupon redemption, payment)
- [x] Payments: `POST /api/payments/{id}/verify/` + `POST /api/orders/{n}/retry-payment/`; MockPaymentProvider supports success / failed / cancelled (new `VerificationResult.cancelled`); row locks prevent double capture; forged signatures fail. COD confirms immediately. Razorpay stays a Phase 8 stub behind the same interface
- [x] Cancellation: state-machine rules unchanged (pending/confirmed/processing); now also records a *pending* Refund for captured payments (no fake refund) and releases the coupon use
- [x] Notifications foundation (`notifications/services.notify`): in-app + email via Django email backend (console in dev), after commit only; events `order.placed`, `order.confirmed`, `order.cancelled`, `payment.failed`
- [x] API additions (non-breaking): cart lines gain image/brand/attributes/MRP totals/discount/limit; order list gains item names/image/delivery message; order detail gains refunds, `can_cancel`, `can_retry_payment`, item images/slugs, `delivery_message`
- [x] Frontend: cart page (images, variant attributes, MRP/discount, stock + price-change notices, save for later, blocked checkout on conflicts, sticky mobile bar), checkout (address select/add/edit/delete/default, delivery info, items, coupon apply/remove with server reasons, server order summary, COD / mock online, delivery note, sticky mobile CTA, double-submit safe), mock payment page (success/failure/cancel, retry, cancel order), order confirmation, order history (paginated), order detail (timeline of real statuses, price snapshot, payment/refund info, cancel dialog with reasons), addresses page; checkout/account routes lazy-loaded (main bundle < 500 kB)
- [x] Django admin verified by test: orders (+ items, status history), payments, refunds, notifications, customers; payments/orders cannot be added or edited by hand
- [x] Tests: backend 168 pass (new `orders/tests/test_checkout.py` 26, `orders/tests/test_admin.py`); frontend 70 pass across 10 files (new checkout, payment/orders/confirmation/addresses, rewritten cart tests)
- [x] Verified: ruff lint clean, `check` clean, `makemigrations --check` clean, migration applied to the dev DB (no reset); frontend lint/typecheck clean, production build OK; OpenAPI generates with 0 errors (4 cosmetic enum-name warnings)
- [x] Live end-to-end (29 checks, real dev DB + demo catalogue, 2 temporary customers deleted afterwards): address required, invalid/minimum-order coupon reasons, valid DEMO10 discount, quantity limit, changed-total rejection, COD order, idempotent replay, double submit, mock success/failure/retry/cancel, cancel unpaid and paid (pending refund), cross-customer 404s, status-change 403/405, history order; notifications recorded and reserved stock back to 0
- [~] Live stock check used the product's order limit; the "stock dropped after adding to cart" path is covered by backend tests (inventory reduced directly), not by the live run
- [~] Browser testing NOT performed: Chrome again showed an error page for the local server

## Phase 6 — Offer engine + coupon discovery ✅ (2026-09-24)
Scope: ROADMAP Phase 6 ("server cart, coupon engine, checkout preview"). Cart, wishlist, coupon validation and checkout preview already existed (Phases 2/5); the open item was TASKS' "Offers are stored but not auto-applied (Phase 6)".
- [x] `offers/engine.py`: automatic offers — live window, product/category targets (categories include subcategories; none = whole cart), one offer per line with lowest `priority` winning, minimum spend on the offer's own lines with fallback to the next offer, percent (capped) or fixed (≤ eligible), Decimal pro-rata spread per line, "add ₹X more" missed offers, customer badges
- [x] `orders.pricing.price_lines`: single pricing path (cart, checkout preview, coupon preview, available coupons, order placement): offers first, then the coupon on the post-offer amount (coupon minimums evaluated after offers); GST per line on the net amount; `Totals` gains `offer_discount`/`coupon_discount` (`discount_total` = both; old callers unchanged)
- [x] Orders store `offer_discount`, `coupon_discount`, `applied_offers` snapshot and per-item `offer_discount`; `CouponRedemption.discount_amount` is now the coupon portion only; migration `orders 0003` back-fills `coupon_discount` for existing orders (migration test); an offer starting/ending mid-checkout → 409 `totals_changed`
- [x] APIs (additive): cart `offers {applied, missed}` + new total fields; checkout preview `offers`; product `offer` badge (one offers query per response); `GET /api/offers/` (public); `GET /api/coupons/available/` (customer; `Coupon.show_in_checkout` opt-in, migration `offers 0003`, usage limits respected, applicability + reason per coupon)
- [x] Django admin: offer fieldsets with target help text, editable priority/active, "Live now" column; coupon `show_in_checkout` (list-editable)
- [x] Demo data: 3 "Demo:" offers (Tools week 10% up to ₹400 on ₹1,500 of tools; Safety first ₹50 off ₹500; Plumbing fittings 5%); DEMO10/DEMOFLAT50 advertised at checkout
- [x] Frontend: offer badge on product cards (text, not colour only; hidden when out of stock), product page callout, homepage "Offers running now" (hidden when none), cart applied-offer notes + unlock hints, per-offer and coupon rows in every price summary, checkout "Available coupons" with one-tap apply and server reasons, order detail offer rows + per-item "Offer saving"; cart/wishlist/login/register routes lazy-loaded (main bundle 327 kB)
- [x] Tests: backend 187 pass (18 new offer/stacking/API tests in `offers/tests/test_offers.py`, 1 migration back-fill test); frontend 76 pass across 11 files (6 new offer UI tests)
- [x] Verified: ruff lint clean, `check` clean, `makemigrations --check` clean, migrations applied to the dev DB and demo offers seeded (no reset); frontend lint/typecheck clean, production build OK (no size warning)
- [x] Live end-to-end (18 checks, dev DB + demo catalogue, temporary customer and 2 cancelled test orders removed afterwards): public offers, badges on targeted products only, minimum-spend hint then capped application, fixed offer, two offers on separate lines, available coupons with verdicts, coupon stacked after offers, totals arithmetic, order breakdown + snapshot + per-item shares, 401/405 checks
- [~] Browser testing NOT performed (same local-browser limitation as Phases 4–5; not re-attempted)
- [x] Housekeeping: `ruff format` applied to the 6 Phase 3 accounts/delivery files noted above (formatting only); the whole backend is now format-clean

## Known limitations carried forward
- Store selection picks the first store covering all items (distance/zone/ETA selection is Phase 9); `delivery.eta_minutes` is always null until then
- Offers have no usage limits or per-customer caps, no "buy X get Y"/bundle or free-delivery offer types, and only one coupon per order; offers are managed in Django admin only (dashboard in Phase 11)
- Product listing prices stay the catalogue price; the offer discount appears in the cart (the badge says so), not as a reduced list price
- Online payments use the mock gateway; Razorpay, webhooks and refund *processing* are Phase 8 (refunds are recorded as pending)
- Unpaid online orders keep their stock reserved until paid or cancelled; automatic expiry of abandoned payments needs the Phase 8/20 job queue
- Notifications are in-app records + email only; there is no in-app notification list screen yet (Phase 20)
- Cart "save for later" uses the wishlist (per product, not per variant)
- Search is keyword/substring based (no typo tolerance or synonyms; "tap" also matches "tape"); semantic search is Phase 13
- Specification filters need consistent spec names/values in the admin; variant-level attributes (e.g. wire length) are shown on the product page but are not yet filterable
- The location selector only remembers a PIN code; serviceability/ETA per address is Phase 9
- Product/category pages set title and meta description client-side (no server rendering or sitemap yet)
- Delivery assignment workflow (accept, pickup, OTP, proof) is Phase 10; partners are verified by admins in Django admin
- Email verification is not implemented yet (`email_verified` is reset on email change)
- A local dev server stopped with `Stop-Process -Force` makes Git Bash report exit 127 (the venv `python.exe` launcher loses its child); stop it with Ctrl+C in normal use
- `core.Job` DB queue deferred to Phase 8/20, when the first background job exists

## Later phases
See docs/ROADMAP.md (Phases 3–24).

## Environment notes
- Repo is inside OneDrive: consider excluding `backend/.venv` and `frontend/node_modules` from sync.
- Node is portable (not on PATH). Prefix commands with `$env:PATH="$env:LOCALAPPDATA\tools\node-v24.21.0-win-x64;$env:PATH"` or install Node LTS system-wide.
