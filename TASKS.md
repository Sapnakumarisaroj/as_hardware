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

## Phase 3 — Authentication + roles (next, not started)
- [ ] Register, login, refresh, logout (blacklist), forgot/reset password, `me` profile endpoints; auth throttles
- [ ] Role assignment rules (customers self-register; staff, delivery and admin roles are set by admins)

## Known limitations carried forward
- Store selection picks the first store covering all items (distance/zone/ETA selection is Phase 9)
- Offers are stored but not auto-applied (Phase 6); coupons work
- Online payments create a mock intent only; verification, webhooks and refunds are Phase 8
- Keyword `q` search is a basic `icontains`; full-text/typo-tolerant search is Phase 4
- Staff permissions are global (not scoped per store) until Phase 11
- `core.Job` DB queue deferred to Phase 8/20, when the first background job exists

## Later phases
See docs/ROADMAP.md (Phases 3–24).

## Environment notes
- Repo is inside OneDrive: consider excluding `backend/.venv` and `frontend/node_modules` from sync.
- Node is portable (not on PATH). Prefix commands with `$env:PATH="$env:LOCALAPPDATA\tools\node-v24.21.0-win-x64;$env:PATH"` or install Node LTS system-wide.
