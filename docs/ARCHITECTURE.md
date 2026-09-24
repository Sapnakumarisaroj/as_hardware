# BoltRun — Architecture

> Working name: **BoltRun** (AI hardware marketplace with ~60-minute delivery).
> Configurable via `APP_NAME` / `VITE_APP_NAME`; rename at any time.

## 1. Goals and constraints

- A real full-stack application: relational database, JWT auth, REST APIs, and transactional order/inventory logic.
- **Deploys to the owner's existing paid web hosting.** No additional paid infrastructure unless the owner explicitly approves it.
  The hosting type is **not yet confirmed** (see `docs/DEPLOYMENT.md` §0), so the design assumes the *most restrictive
  common case*, shared cPanel-style hosting:
  - Python app served by **Phusion Passenger** (WSGI, no long-running processes of our own)
  - **MySQL/MariaDB** possibly the only database
  - **cron** available; **no Docker, Redis, Celery, or background workers**
  - limited RAM/CPU, so **no local LLM in production**
  If the host turns out to be a VPS, the same code runs unchanged with PostgreSQL and gunicorn.
- AI answers about purchasable products are **grounded in the catalog database**. Price, stock and availability always come from DB queries, never from model output.
- Every external service sits behind a **provider interface** with a free/mock default. Mock providers are clearly labelled and never report a fake external success as real.
- The app stays runnable after every phase.

## 2. System overview

```
 Browser ──▶ https://yourdomain.com          static SPA (dist/: index.html + assets, .htaccess SPA fallback)
         └─▶ https://api.yourdomain.com/api/  Django + DRF via Passenger (passenger_wsgi.py)
                                                ├── apps/ (domain modules, service layer)
                                                ├── integrations/ (provider adapters)
                                                └── apps/ai (AIService facade)
                                                      │
                          ┌───────────────────────────┼─────────────────────────────┐
                          ▼                           ▼                             ▼
                 DB from hosting plan         Media folder on host         Optional external APIs
          (PostgreSQL if offered, else MySQL) (MEDIA_ROOT, web-served)  (Razorpay, WhatsApp Cloud,
                                                                          LLM API; all opt-in)
 cron (every 1–5 min) ──▶ manage.py run_jobs   drains the DB-backed job queue (notifications, AI batch tasks)
```

**Local development (Windows + VS Code):** Django `runserver` and the Vite dev server. The database is SQLite by default,
with optional local PostgreSQL/MySQL matching production. Ollama provides a free local LLM. `docker-compose.yml` is an
**optional local convenience only** and is never required for production.

## 3. Repository layout

```
as_hardware/
├── backend/
│   ├── config/settings/     base / dev / test / prod (all env-driven)
│   ├── apps/                (✅ = models + services exist as of Phase 2)
│   │   ├── core/            ✅ base models, soft delete, health, errors, request ID, audit log, permissions,
│   │   │                       money helpers, validators, upload paths, seed_demo_data command, test builders
│   │   ├── accounts/        ✅ User + roles, CustomerProfile, Address (+ API); auth flows in Phase 3
│   │   ├── catalog/         ✅ Category tree (+ SubCategory proxy), Brand, Product, ProductVariant, images, specs (+ API)
│   │   ├── stores/          ✅ Store (store / dark store / warehouse) + Warehouse proxy
│   │   ├── inventory/       ✅ Inventory per (store, variant), StockMovement ledger, stock service (+ staff API)
│   │   ├── offers/          ✅ Coupon, CouponRedemption, Offer; coupon rules, automatic offer engine (Phase 6)
│   │   ├── carts/           ✅ Cart, CartItem, Wishlist, WishlistItem (+ API)
│   │   ├── orders/          ✅ Order, OrderItem (snapshots), OrderStatusHistory, state machine, pricing, placement (+ API)
│   │   ├── payments/        ✅ Payment, Refund (verification/webhooks in Phase 8)
│   │   ├── delivery/        ✅ DeliveryZone, DeliveryPartner, DeliveryAssignment, DeliveryStatusHistory (logic Phase 9–10)
│   │   ├── reviews/         ✅ Review (verified buyers only, moderation) (+ API)
│   │   ├── notifications/   ✅ Notification (sending in Phase 20)
│   │   ├── support/         ✅ SupportConversation, SupportMessage (channels in Phase 20)
│   │   ├── ai/              ✅ AIConversation, AIMessage, Project, ProjectItem (AI logic Phases 12–19)
│   │   └── analytics/       🔜 whitelisted reporting queries + business assistant (Phase 21)
│   ├── integrations/        payments/ ✅ (PaymentProvider + MockPaymentProvider); llm/, messaging/, maps/ 🔜
│   ├── passenger_wsgi.py    shared-hosting entry point
│   └── requirements/        base / dev / prod / mysql
├── frontend/                React 19 + TS + Vite + Tailwind v4; builds to static dist/
├── docs/                    ARCHITECTURE, DATABASE, API, ROADMAP, DEPLOYMENT
├── docker-compose.yml       OPTIONAL local stack
├── .env.example
└── TASKS.md
```

## 4. Backend layering

| Layer        | File(s)          | Responsibility |
|--------------|------------------|----------------|
| Models       | `models.py`      | schema, constraints, indexes |
| Selectors    | `selectors.py`   | read queries (`select_related`/`prefetch_related`) |
| Services     | `services.py`    | write workflows in `transaction.atomic`; the only place state transitions happen |
| Serializers  | `serializers.py` | validation and output shaping |
| Views        | `views.py`       | thin: permissions → serializer → service/selector |
| Permissions  | `permissions.py` | role and object-level rules |
| Tests        | `tests/`         | pytest-django |

### Database portability (PostgreSQL ⇄ MySQL/MariaDB ⇄ SQLite)
The production vendor is unknown, so models use only portable Django features:
- `JSONField` instead of `ArrayField`/`HStoreField`, and no `django.contrib.postgres` imports in models.
- Uniqueness that needs a condition (e.g. one default address per user) is enforced in the service layer under
  `select_for_update`, backed by a plain unique constraint where possible, because MySQL has no partial indexes.
- `CheckConstraint` works on PostgreSQL, MySQL 8.0.16+ and MariaDB 10.2+. Services validate the same rules as well.
- Row locking (`select_for_update`) works on PostgreSQL and MySQL/InnoDB. SQLite serialises writes, which is acceptable locally.
- The migration test suite runs against SQLite locally. CI and pre-deploy runs use the production vendor.

### Dependency direction between apps
`core` ← everything. `catalog`, `stores` ← `inventory` ← `carts`/`orders`. `orders.pricing` is the single price/tax/fee
calculator shared by the cart and checkout (no duplicated money logic). `offers.services` validates coupons against
duck-typed priced lines, so it doesn't import `orders`. Views never call other apps' models directly for writes; they
call services.

### Order state machine (implemented in Phase 2: `orders/state_machine.py`)
`pending → confirmed → processing → packed → assigned → picked_up → out_for_delivery → delivered`,
with exits `cancelled` (before pickup) and `return_requested → returned`. `orders.services.transition_order()` validates
each transition and writes an `OrderStatusHistory` row in the same transaction.

### Inventory integrity
Stock is held per `(store, variant)` with `quantity` and `reserved`. Checkout locks rows (`select_for_update`), reserves
stock, and logs a `StockMovement`, all in one transaction.

### Checkout and order flow (Phase 5)
```
Cart ──► POST /checkout/preview/ (orders/checkout.py: build_checkout — read-only)
         re-prices the cart, validates stock/availability, address, coupon, quotes delivery, lists blocking issues
     ──► POST /orders/  + Idempotency-Key + expected_total (orders/services.py: place_order — one transaction)
         lock cart row → same key? return that order → lock cart lines/coupon → validate → recalculate (Decimal)
         → expected_total differs? 409 totals_changed → choose store → Order + OrderItems (snapshots)
         → reserve stock (ledger) → coupon redemption → status history → Payment (COD record | gateway intent)
         → COD: confirm → clear cart → notifications queued with transaction.on_commit
     ──► online: POST /payments/{id}/verify/ (payments/services.py) → provider verifies → captured/failed/cancelled
         → paid orders are confirmed; failed/cancelled attempts can be retried (/orders/{n}/retry-payment/)
```
- **Money** is recalculated on the server from current catalog prices on every preview and again at placement
  (`orders/pricing.py`, `Decimal`, half-up to paise). The client's `expected_total` is only *compared*; a mismatch means
  a price, stock-driven line or coupon changed, and nothing is created.
- **Idempotency**: the browser creates one key (`crypto.randomUUID()`) per checkout attempt and sends it on every retry.
  Unique `(user, idempotency_key)` plus the cart-row lock make a double click or network retry return the first order.
  Without a key, a second submit fails with `cart_empty` because the first order cleared the cart.
- **Payments**: business code only talks to `integrations.payments.PaymentProvider`. `MockPaymentProvider` (dev) signs
  each intent with HMAC; the browser returns `{mock_signature, mock_outcome}` and the server verifies it, so a forged
  "success" is rejected. Razorpay implements the same interface in Phase 8; production refuses to start with the mock.
- **Cancellation** follows the state machine (`CUSTOMER_CANCELLABLE` = pending/confirmed/processing). It releases stock,
  voids uncaptured payments, records a *pending* Refund for captured money (no refund is faked; Phase 8 processes it) and
  returns the coupon use.
- **Delivery information** (`quote_delivery`) reports availability (one store can supply every line), fee, free-delivery
  threshold and whether that store has a fast-delivery zone. `eta_minutes` stays `null`; the UI says the estimate is
  confirmed after ordering. Phase 9 replaces `find_fulfilment_store`/`quote_delivery` with the distance/ETA engine
  without changing the API shape.
- **Notifications** (`notifications/services.notify`): in-app rows plus email through Django's email backend (console in
  dev), sent only after commit so rolled-back orders never notify. SMS/WhatsApp providers are Phase 20.

### Offers and coupons (Phase 6)
One pricing path, `orders.pricing.price_lines(lines, coupon=None)`, is used by the cart, checkout preview, coupon
preview, available-coupon list and order placement, so every screen and the stored order agree to the paisa.

```
cart lines (current catalogue prices)
  └─► offers.engine.apply_offers  — automatic, no code
        · live = is_active and starts_at ≤ now < ends_at (no end = open-ended)
        · targets: products and/or categories (a category includes its subcategories); none = whole cart
        · ONE offer per line; overlapping offers → lowest `priority` number wins (tie: older offer)
        · min_order_value is measured on the lines the offer won; if missed, those lines fall to the
          next-best offer (repeat until stable) and the offer is reported as "add ₹X more to unlock"
        · percent (capped by max_discount_amount) or fixed (never above the eligible amount);
          spread over the offer's lines pro rata (remainder on the last line)
  └─► coupon (offers.services) on what remains after offers
        · all existing rules: dates, usage and per-customer limits, product/category scope,
          and min_order_value — evaluated on the post-offer amount
  └─► calculate_totals: GST per line on its net amount; delivery fee on the final net
```
- **Stacking policy**: offers and one coupon stack; the coupon never discounts money an offer already took off.
- **Orders** snapshot the result: `offer_discount`, `coupon_discount` (their sum is `discount_total`),
  `applied_offers` (id, name, badge, discount, SKUs) and each item's `offer_discount`, so later offer edits never change
  a past order and Phase 7 returns can refund the right amount per line.
- **Changing offers mid-checkout**: if an offer starts/ends between preview and "Place order", the recalculated total
  differs from `expected_total` → 409 `totals_changed`; the customer sees the new total first.
- **Badges**: product cards/pages show the best live offer (`ProductListSerializer.offer`); active offers are loaded
  once per API response (a few rows + two small prefetches), matched in Python — portable and cheap.
- **Coupon discovery**: coupons are private by default; admins tick `show_in_checkout` to list one under "Available
  coupons", where each is evaluated against the customer's cart (applies / why not).
- Admins manage offers in Django admin (Offers: targets, priority, schedule, "Live now" column). There is no customer
  or staff write API for offers until the Phase 11 dashboard.

### Delivery ETA engine (Phase 9)
`eta = prep_time(store, items) + queue_delay(open orders per available partner) + travel_time(distance)`.
The distance is the haversine distance between store and address (free, offline) × a road-factor ÷ the configured average
speed, flagged `eta_source: "estimate"`. A routing API can be plugged in later. Fast delivery is offered when
`eta ≤ FAST_DELIVERY_MAX_MINUTES`; otherwise the engine returns the next available slot.

### Background jobs without Celery/Redis
`core.Job` table (Phase 8/20) plus `enqueue(job_name, payload)`.
- `BACKGROUND_JOBS_MODE=inline`: the job runs immediately (local dev, simplest).
- `BACKGROUND_JOBS_MODE=cron`: cron runs `python manage.py run_jobs --max-seconds 50` every minute, claims rows with
  `select_for_update(skip_locked=True)` (falling back to an optimistic claim on MariaDB < 10.6), and retries with backoff.
Payment and order correctness **never** depend on a background job; notifications and AI batch work do.

## 5. AI architecture

```
apps/ai/services/
  AIService (facade)
   ├── ProductSearchAI          query → structured filters → catalog search
   ├── HardwareAssistant        intent detection + tool calls over catalog tools
   ├── VisionProductIdentifier  image → {category, attributes, confidence} → catalog search
   ├── VoiceShopping            STT → HardwareAssistant → optional TTS
   ├── ProjectBuilder           guided questions → kit from real products
   ├── QuantityCalculator       deterministic formulas (paint, tiles, wire, pipe, cement, screws, adhesive)
   ├── CompatibilityChecker     spec rules + optional LLM explanation
   ├── SmartCart                complementary products (rules + co-purchase data)
   ├── RecommendationEngine     history/cart/category; honours opt-out
   ├── ReviewSummarizer         real reviews only
   ├── ProductDataGenerator     admin drafts requiring approval
   └── BusinessAnalyticsAssistant  picks from whitelisted analytics queries only
integrations/llm/
  LLMProvider (chat, chat_with_tools, vision, embed) + capability flags
   ├── NoLLMProvider         default: rule/keyword-based fallbacks, responses flagged `ai_mode: "basic"`
   ├── OllamaProvider        local dev (free): e.g. llama3.1/qwen2.5 for chat, llava/qwen2.5-vl for vision
   ├── OpenAICompatibleProvider  any OpenAI-compatible endpoint (self-hosted or paid; owner opts in)
   └── AnthropicProvider     optional; owner opts in
```
- **Production:** shared hosting cannot run an LLM (RAM/CPU/process limits). Production defaults to `LLM_PROVIDER=none`,
  so every AI feature still works in a deterministic "basic" mode (keyword search, calculators, spec-rule compatibility,
  co-purchase suggestions). Nothing subscribes to a paid API automatically.
- **Speech:** STT/TTS interfaces. The default uses the browser's Web Speech API (free, client-side) where supported, with
  server-side providers pluggable later.
- **Grounding, enforced in code:** the LLM reaches products only via tools; product cards are built from DB rows; cited IDs
  are re-validated; quantities come from Python formulas and are labelled as estimates; unknown specs give
  `insufficient_information`; the analytics assistant cannot run free-form SQL; low-confidence vision results show "possible matches".
- **Search:** a `SearchBackend` interface chosen by `DB_VENDOR`:
  - PostgreSQL: full-text `SearchVector` + `pg_trgm` trigram similarity (typo tolerance).
  - MySQL/SQLite: token `icontains` over name/brand/SKU/tags/specs, plus a typo-tolerant pass that corrects each query term against a cached vocabulary table using `difflib`.
  - Semantic (Phase 13): embeddings stored as JSON vectors with in-Python cosine similarity, fine for catalogs up to roughly 10–20k products and needing no pgvector. Enabled only when an embedding provider is configured.

## 6. Integrations (provider pattern)

| Concern   | Default (free)                         | Optional production provider     | Switch |
|-----------|----------------------------------------|----------------------------------|--------|
| Payments  | `MockPaymentProvider` (dev only; prod refuses it) + COD | Razorpay (UPI, cards, net banking, refunds, webhooks) | `PAYMENT_PROVIDER` |
| WhatsApp  | `MockWhatsAppProvider` (stores and logs messages)  | WhatsApp Business Cloud API (Meta) | `WHATSAPP_PROVIDER` |
| SMS       | `MockSMSProvider`                      | MSG91 / Twilio                   | `SMS_PROVIDER` |
| Email     | console backend (dev)                  | hosting mailbox SMTP             | `EMAIL_*` |
| Maps      | OpenStreetMap tiles + **Leaflet** (frontend), Nominatim geocoding (rate-limited, cached), haversine distance | Google Maps | `MAPS_PROVIDER` |
| LLM       | `NoLLMProvider` / Ollama (local)       | OpenAI-compatible / Anthropic    | `LLM_PROVIDER` |
| Storage   | local filesystem (`MEDIA_ROOT`)        | S3-compatible (only if approved) | `STORAGE_BACKEND` |

Webhooks (Razorpay `X-Razorpay-Signature`, WhatsApp `X-Hub-Signature-256`) are HMAC-verified and idempotent (the event ID is unique).
Nominatim's usage policy (1 req/s, identifying User-Agent) is respected: geocodes are cached in the DB, and address pins come from the user's map click whenever possible.

## 7. Security
- Argon2 password hashing. JWT with 15-minute access tokens and rotating, blacklisted refresh tokens.
- Roles `customer`, `store_staff`, `delivery_partner` and `admin`, with DRF permissions and object-level checks.
- Throttle scopes: anon, user, auth and ai. Throttle state uses Django's cache, which on shared hosting is the DB cache
  table (no Redis).
- CORS allow-list. CSRF protects the session-auth Django admin. SPA and API on separate subdomains.
- Upload validation: type, size and Pillow verification, with random filenames.
- Secrets come only from environment variables (control-panel variables or a `.env` outside the web root).
- `AuditLog` for admin and sensitive actions. `prod` settings add HSTS, secure cookies and `check --deploy`.
- `PAYMENT_PROVIDER=mock` raises at startup in production unless explicitly overridden for staging.

## 8. Frontend
React 19 + TypeScript (strict) + Vite 8 + Tailwind v4 (charcoal + safety-amber industrial theme), React Router,
TanStack Query, and Axios (normalised `ApiError` matching the backend envelope). Builds to static files, so **Node.js is
not needed on the server**. `public/.htaccess` gives Apache the SPA fallback and cache headers. Vitest + Testing Library.

### Customer catalog (Phase 4)
```
src/
  app/            routes, AppProviders (toasts, auth, pending-action runner), layouts (Header, Footer)
  components/     generic UI: feedback states, Drawer, Pagination, QuantityStepper, toasts, icons
  features/
    auth/         AuthProvider (mirrors /auth/me/), token store, pending action (wishlist/cart before login)
    catalog/      API hooks, types, URL listing state, ProductCard/Grid/Rail, FilterPanel, ProductBrowser,
                  ProductGallery, VariantSelector, badges (price/stock/rating)
    search/       SearchBar (type-ahead, recent searches), search API hooks
    cart/ wishlist/ location/
  pages/          Home, Category (/c/:slug), Search (/search, /products), ProductDetail (/p/:slug), Cart, Wishlist, auth, account
```
- **Server is the source of truth.** Price, MRP, discount, stock status, fast-delivery eligibility and cart totals come
  from the API as decimal strings. The browser only formats them (`lib/format.ts`) and never does money arithmetic. Cart
  and wishlist buttons send ids and quantities; stock and price are validated by the backend, and its error messages
  ("Only 2 available") are shown as toasts.
- **Listing state lives in the URL** (`useListingState`): `q`, filters, `ordering` and `page` are query parameters, so
  results are shareable and Back/Forward work. The same params go to `/products/` (paginated, 24 per page) and
  `/products/facets/` (filter options). Nothing is filtered or sorted client-side.
- **Filters are data-driven.** The facets endpoint decides which brand/price/rating/discount/availability/specification
  filters apply to the current results, so a drill category shows power and chuck size while wires show area and length.
- **Variants.** Every sellable unit is a variant. The product page selects one (`?variant=<id>` in the URL); price, MRP,
  saving, SKU, stock, delivery badge, variant attributes (shown in the spec table) and variant-specific images switch with
  it. Product cards with more than one variant link to "Choose options" instead of guessing a variant.
- **Search service.** The UI only calls `/products/?q=` and `/search/suggest/`. The backend search engine is pluggable
  (`CATALOG_SEARCH_BACKEND`). Phase 13 can switch to semantic/hybrid search without frontend changes. "Ask AI" in the
  header is a clearly labelled "coming soon" entry point, not a fake assistant.
- **Delivery honesty.** Product pages say "Fast delivery available from a nearby store" only when the variant is stocked at
  a store with a fast-delivery zone, and always add that availability/time is confirmed after address selection. No fixed
  "60 minutes" promise until the Phase 9 ETA engine exists.
- **Logged-out actions** (wishlist/cart) are saved in `sessionStorage`, the shopper is sent to login with `?next=`, and
  `PendingActionRunner` completes the action after sign-in, so nothing is silently lost.
- **Caching.** TanStack Query: categories/brands 10 min stale time, facets 1 min, suggestions 1 min (debounced 250 ms),
  `keepPreviousData` on listings so the grid stays visible while the next page loads. Wishlist removal is optimistic
  (safe to roll back); cart updates are not (server reply replaces the cache).
- **Images.** `ProductImage` files are stored through Django's storage API (local `MEDIA_ROOT` now; S3/Cloudinary later by
  changing `STORAGES` only). The UI lazy-loads images and shows a labelled placeholder when an image is missing or broken.
  Demo images are drawn locally with Pillow by `seed_demo_data` and are marked "DEMO IMAGE".
- **SEO basics.** Readable slug URLs (`/c/<slug>`, `/p/<slug>`), per-page `<title>` and meta description (`usePageMeta`).
- **Accessibility.** Semantic landmarks, labelled controls, combobox/listbox search, radio-group variant picker, visible
  focus rings, text (not colour or icons alone) for stock and discount, `aria-live` for counts and toasts.
- **Responsive.** Header wraps search to its own row on mobile with a hamburger menu; filters become a drawer; the product
  page gets a sticky add-to-cart bar; product rails scroll horizontally.

### Checkout and orders (Phase 5)
Routes: `/cart` → `/checkout` → `/orders/:number/pay` (online) → `/order-confirmation/:number`; `/account/orders`,
`/account/orders/:number`, `/account/addresses`. Checkout, payment and account pages are lazy-loaded route chunks.
- `features/checkout`: `useCheckoutPreview(addressId, coupon)` — every change of address or coupon asks the server again
  (`staleTime: 0`, previous result kept on screen while refetching). Coupons are applied only after the server accepts
  them; its reason is shown when it doesn't.
- `features/orders`: typed API hooks (place, cancel, retry payment, verify payment), status labels, timeline builder
  (only statuses the order really reached, then the normal steps still ahead; cancelled orders show no future steps),
  `PriceSummary` (formats server strings, never adds them), cancel dialog with reasons.
- `features/addresses`: add/edit modal with the server's field errors, list with select/default/delete; used by checkout
  and the account page.
- Cart/checkout mutations invalidate the cart and checkout queries; order results are written into the order cache so
  pages update from the server's response.
- Mobile: single-column checkout, sticky total/CTA bar, ≥ 44 px touch targets for address and payment choices, bottom-
  sheet dialogs.

### Offers UI (Phase 6)
`features/offers`: `OfferBadge` on product cards (text "Offer: 10% off", not colour alone), `ProductOfferCallout` on the
product page ("applied automatically in your cart"), `CartOfferNotes` (applied offers + "add ₹X more to unlock"),
`AvailableCouponList` at checkout (server verdict per coupon, one-tap apply) and `LiveOffersStrip` on the homepage
(hidden when no offers run). `PriceSummary` shows one row per applied offer and a separate coupon row. Cart, wishlist
and login/register routes are now lazy-loaded too (main bundle ≈ 327 kB).

## 9. Environments
| | Local (Windows) | Production (existing hosting) |
|---|---|---|
| Backend | `manage.py runserver` | Passenger → `passenger_wsgi.py` (gunicorn if VPS) |
| Frontend | Vite dev server | static `dist/` uploaded to the document root |
| DB | SQLite (default) or local Postgres/MySQL | hosting DB (PostgreSQL preferred, else MySQL) |
| Static | Django dev server | WhiteNoise (served by the Python app) |
| Media | `backend/media/` | web-served folder on the host (`MEDIA_ROOT`) |
| Jobs | inline | cron → `run_jobs` |
| AI | Ollama (optional) | `none` until the owner chooses a provider |

## 10. Environment notes
- The repo sits inside a **OneDrive-synced folder**. Syncing `node_modules/` and `.venv/` is slow and can lock files.
  Consider moving the repo outside OneDrive or excluding those folders.
- Local toolchain: Python 3.11 (venv), portable Node 24 LTS at `%LOCALAPPDATA%\tools\node-v24.21.0-win-x64`
  (not on the system PATH), and Docker Desktop (optional).
