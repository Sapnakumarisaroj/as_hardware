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
│   │   ├── payments/        ✅ Payment, Refund, WebhookEvent; verification, webhooks, refunds, reconciliation, jobs
│   │   ├── delivery/        ✅ zones, PIN codes, fulfilment + ETA engine (Phase 9); riders, assignments, rider workflow,
│   │   │                       delivery code, proof of delivery, cash on delivery (Phase 10) (+ rider and staff API)
│   │   ├── reviews/         ✅ Review (verified buyers only, moderation) (+ API)
│   │   ├── notifications/   ✅ Notification (sending in Phase 23)
│   │   ├── support/         ✅ SupportConversation, SupportMessage (channels in Phase 23)
│   │   ├── ai/              ✅ AIConversation, AIMessage, Project, ProjectItem (AI logic Phases 12–19)
│   │   └── analytics/       🔜 whitelisted reporting queries + business assistant (Phase 24)
│   ├── integrations/        payments/ ✅ (PaymentProvider, MockPaymentProvider, RazorpayPaymentProvider); maps/ ✅ (Phase 9);
│   │                        llm/, messaging/ 🔜
│   ├── private_media/       proof-of-delivery photos: NOT web-served, not in git (PRIVATE_MEDIA_ROOT)
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
- Row locking (`select_for_update`) works on PostgreSQL and MySQL/InnoDB. SQLite serialises writes; its transactions run
  in `IMMEDIATE` mode (Phase 7) so concurrent requests wait for the write lock instead of erroring. The tests use a
  temporary file database because SQLite's in-memory test database cannot wait on locks across threads.
- The migration test suite runs against SQLite locally. CI and pre-deploy runs use the production vendor.

### Dependency direction between apps
`core` ← everything. `catalog`, `stores` ← `inventory` ← `carts`/`orders`. `orders.pricing` is the single price/tax/fee
calculator shared by the cart and checkout (no duplicated money logic). `offers.services` validates coupons against
duck-typed priced lines, so it doesn't import `orders`. Views never call other apps' models directly for writes; they
call services.

### Order state machine (implemented in Phase 2: `orders/state_machine.py`)
`pending → confirmed → processing → packed → assigned → picked_up → out_for_delivery → delivered`,
with exits `cancelled` (before pickup) and `return_requested → returned`. `orders.services.transition_order()` validates
each transition and writes an `OrderStatusHistory` row in the same transaction. Phase 10 adds `delivery_failed`
(reached from `packed`…`out_for_delivery`; leaves to `assigned`/`packed` for another attempt, or `cancelled`) and
derives the order status from its shipments once it is packed (see *Delivery partner workflow*).

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
     ──► online: Razorpay Checkout (or the dev mock) in the browser → POST /payments/{id}/verify/
         → signature check + server-side fetch from the gateway → captured / failed / cancelled / still pending
     ──► gateway → POST /payments/webhooks/razorpay/ (HMAC over raw body, event id unique) → same state change
     ──► cron run_jobs: reconcile open attempts with the gateway · expire unpaid orders · submit/poll refunds
         → paid orders are confirmed; failed/cancelled attempts can be retried (/orders/{n}/retry-payment/)
```
- **Money** is recalculated on the server from current catalog prices on every preview and again at placement
  (`orders/pricing.py`, `Decimal`, half-up to paise). The client's `expected_total` is only *compared*; a mismatch means
  a price, stock-driven line or coupon changed, and nothing is created.
- **Idempotency**: the browser creates one key (`crypto.randomUUID()`) per checkout attempt and sends it on every retry.
  Unique `(user, idempotency_key)` plus the cart-row lock make a double click or network retry return the first order.
  Without a key, a second submit fails with `cart_empty` because the first order cleared the cart.
- **Payments** (Phase 8): business code only talks to `integrations.payments.PaymentProvider` (create order, verify,
  fetch attempts, capture, idempotent refund, refund status, parse webhook). `RazorpayPaymentProvider` uses Razorpay's
  REST API over the standard library (`urllib`), with no SDK. `MockPaymentProvider` implements the same interface for
  development and tests (HMAC-signed intents and webhooks, instant refunds). **The browser never decides**: a checkout
  response is trusted only after its HMAC signature matches *and* the payment fetched from the gateway has the right
  order, amount and currency. Webhooks and reconciliation are gateway-originated. All three paths end in the same
  `_record_capture` / `_record_failure`, which are idempotent and never un-capture. Money that arrives for a cancelled
  or already-paid order, or with the wrong amount, is refunded automatically. The Razorpay key secret and webhook
  secret stay in `.env`; the browser only gets the public key id and order id. No card/UPI/bank details are stored:
  webhook payloads are whitelisted to ids, amounts, statuses and error text. Production refuses to start with the mock,
  or with Razorpay but missing credentials; the API base must be `https://`.
- **Refunds** (`payments/refunds.py`): recorded `pending`, submitted by a job, polled or updated by webhook until
  `processed`. Payment and order `payment_status` change only then. COD money is refunded by staff (`mark-processed`
  with a reference), because it can't go back through a gateway. Delivery of a COD order records the cash as captured.
- **Unpaid orders** expire after `PAYMENT_EXPIRY_MINUTES` (default 30): `run_jobs` asks the gateway first, then cancels,
  which releases stock and notifies the customer.
- **Cancellation** follows the state machine (`CUSTOMER_CANCELLABLE` = pending/confirmed/processing). It releases stock,
  voids uncaptured payments, records a *pending* Refund for captured money (queued for the gateway; never faked) and
  returns the coupon use.
- **Delivery information** (`quote_delivery`) reports availability (one store can supply every line), fee, free-delivery
  threshold and whether that store has a fast-delivery zone. `eta_minutes` stays `null`; the UI says the estimate is
  confirmed after ordering. Phase 9 replaces `find_fulfilment_store`/`quote_delivery` with the distance/ETA engine
  without changing the API shape.
- **Notifications** (`notifications/services.notify`): in-app rows plus email through Django's email backend (console in
  dev), sent only after commit so rolled-back orders never notify. SMS/WhatsApp providers are Phase 23.

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

### Fulfilment and delivery engine (Phase 9)
`apps/delivery`: `locations.py` (where is the customer) → `fulfillment.py` (which store or stores) → `eta.py` (when) →
`assignment.py` (which rider may carry it). `orders.checkout` and `orders.services.place_order` call
`plan_fulfillment`; the same plan feeds the product page, cart, checkout preview and the order, so they cannot disagree.

**1. Location.** An address resolves to the best available precision: `exact` (map pin from the Leaflet picker, or
the address geocoded once), `pin` (centre of the PIN code, from the admin-managed `PinCode` table or geocoded once)
or `unknown` (only the PIN string).

**2. Delivery zones.** A store delivers to a location if one of its **active** zones covers it: the PIN code is in
the zone's list, or the location is within `radius_km` (straight line) and inside the zone's polygon when one is set.
With no coordinates on either side, only the store's own PIN matches. When several zones of a store cover the
location, the best one is used: fast-delivery zones first, then the lowest fee, then the smallest radius. Only active
stores and dark stores that accept orders count; **warehouses never ship to customers**.

**3. Store selection** (`plan_fulfillment`). This replaced "first store that has everything".
1. Candidates = stores whose zone covers the location.
2. Every candidate holding **all** lines in the required quantity (available stock; reserved units don't count) gets
   an estimate. The best wins: fast-eligible before standard, then lowest ETA, then shortest distance, then store id
   (a stable tie-break). So a farther store that packs quicker or has a free rider can beat a nearer one.
3. If no single store has everything and `SPLIT_FULFILLMENT_ENABLED`: lines are assigned greedily to the store
   covering the most remaining lines (ties: best estimate), up to `MAX_SHIPMENTS_PER_ORDER` (3). A line is never
   divided between stores. The order is fast only if **every** shipment is fast, and its ETA is the latest shipment's.
   One store is always preferred over a split.
4. Otherwise the items are not deliverable there: `out_of_zone`, `location_unknown` or `insufficient_stock`.

One delivery fee per order: the rule of the primary shipment's zone (the shipment with the most lines), falling back
to `DELIVERY_FEE` / `FREE_DELIVERY_MIN_ORDER`.

**4. ETA** (`eta.estimate`, per store → location), in minutes, rounded up:

    eta = preparation + rider wait + travel + handover

| Part | Source |
|---|---|
| preparation | `store.avg_prep_minutes` + `store.prep_minutes_per_item` × (lines − 1) |
| rider wait | capacity of the store right now: riders who can take an order (available, verified app partners below their `max_active_assignments`, plus `store.own_riders`) against the queue (confirmed/processing/packed shipments without a rider). A free rider → 0; otherwise the queue is spread over the riders on shift × `DELIVERY_RIDER_TURNAROUND_MINUTES` |
| travel | `MapsProvider.route(store, customer)`: OSRM when enabled, else haversine × `ROAD_DISTANCE_FACTOR` at `DELIVERY_AVG_SPEED_KMPH`. Without coordinates: `SAME_PIN_DISTANCE_KM` for the store's own PIN, else the zone radius (worst case) |
| handover | `DELIVERY_HANDOVER_MINUTES` |

**Fast delivery** is offered only when the zone enables it, the store is open now (`opening_hours`), a rider can
take the order, and `eta ≤` the zone's `fast_delivery_max_minutes` (else `FAST_DELIVERY_MAX_MINUTES`). Otherwise the
answer is **standard delivery** with the reason: prepared in the current or next opening hours, dispatched in a batch
after `STANDARD_DISPATCH_DELAY_MINUTES`, shown as a `STANDARD_WINDOW_MINUTES` window starting on the next half hour
("Today, 4:30 PM – 6:30 PM" / "Tomorrow, …"). Nothing is hardcoded: every number comes from store, zone, rider and
settings data, and customers see the calculated minutes.

**5. The order.** `place_order` plans inside its transaction, stores the promise on the order (`delivery_type`,
`eta_minutes`, `estimated_ready_at`, `estimated_delivery_at`, window) and one `OrderShipment` per store with its own
estimate and the parts of the calculation (prep / wait / travel, distance, source). An online order is re-estimated
at the same stores when it is paid, because the clock starts then.

**6. Stock safety.** Planning only *reads* stock. Each line is then reserved at **its shipment's store** through
`apply_movement`, which locks the inventory row and re-checks the quantity; if another order took the stock in
between, the whole order rolls back with `insufficient_stock` (no order, no shipment, no reservation anywhere).
Release on cancel, sale on pickup and restock on return all use the line's shipment store. Threaded tests cover
competing orders spread over two stores and competing split orders.

**7. Rider assignment (foundation).** `assign_shipment` locks the order, then the rider, and refuses orders that
aren't waiting for a rider (`invalid_delivery_state`), a shipment that already has an active assignment
(`already_assigned`) and riders who are offline, unverified, too far or at capacity (`partner_unavailable`). A rider
at capacity becomes `busy`; cancelling or unassigning frees them. Threaded tests cover two staff assigning one shipment
and three shipments competing for one rider. What the rider then does with the job is the next section.

**Maps** (`integrations/maps`): `MapsProvider` = geocoder + router, chosen by `GEOCODING_PROVIDER` (`none` |
`nominatim`) and `ROUTING_PROVIDER` (`haversine` | `osrm`). The default is fully offline. Network providers use
the standard library over https only, time out after `MAPS_TIMEOUT_SECONDS`, and any failure falls back to the offline
estimate, so an outage never blocks checkout. Geocoding answers (including "not found") are stored in `GeocodeCache`;
OSRM routes are cached for `ROUTE_CACHE_SECONDS`. OSRM's car timings are never trusted below the configured
two-wheeler speed.

### Delivery partner workflow (Phase 10)
`apps/delivery`: `assignment.py` (who carries a shipment: assign, reassign, unassign, return pickups) →
`workflow.py` (the rider's steps) with `otp.py`, `proof.py` and `cod.py`. `orders/shipments.py` keeps shipments,
stock and the order status consistent.

**1. One job, one rider, fixed steps.** A `DeliveryAssignment` is a delivery or a return pickup.

    Delivery:       assigned ─accept→ accepted ─pickup→ picked_up ─start→ out_for_delivery ─complete→ delivered
    Return pickup:  assigned ─accept→ accepted ─pickup (customer)→ picked_up ─complete (store)→ delivered
    Either:         assigned/accepted ─reject→ rejected · cancelled (by staff, or the order was cancelled)
                    picked_up/out_for_delivery ─fail→ failed

Each step is valid from exactly one status; anything else is refused with `invalid_delivery_state` and changes
nothing (tested for every action × every status). There is no generic "set status" for riders and no writable job
field: the API is a list of actions, each validated on the server.

**2. Shipments carry the progress; the order follows.** Each `OrderShipment` has its own `status` and
`stock_state`. From `packed` onwards the order status is *derived*: `delivery_failed` if any shipment failed,
otherwise the least advanced shipment (`sync_order_status` walks the order through the state machine one valid
transition at a time, so the history shows every step). An order from two stores is therefore "out for delivery"
only when nothing is still waiting at a store, and "delivered" (and a COD order "paid") only when both parts arrived.
Two callers change shipments:
- a **rider's step** changes one shipment, then the order catches up;
- an **order-level change** (staff transition, customer cancel, payment expiry) moves the order and
  `mirror_order_status` brings its shipments along. This path serves stores whose own riders don't use the app.
  While a delivery partner holds a job, staff cannot push the order through the delivery statuses from here
  (`rider_in_charge`): they reassign or unassign instead.

**3. Stock moves once per shipment**, tracked by `stock_state`: `reserved → sold` at pickup (the goods left the
store), or `reserved → released` when the order is cancelled before pickup. After a failed delivery the goods are
back at the store but still belong to the order (`sold`); sending them out again moves no stock, and cancelling the
order then puts them back on the shelf (`sold → restocked`, a `return` stock movement). An order can't be cancelled
while part of it is with a rider or already delivered (`shipment_on_the_way`).

**4. Delivery code (OTP)**, `otp.py`. Six digits, issued when the rider starts the delivery.
- **Never stored.** The code is derived with HMAC-SHA256 from a random per-issue nonce and a key derived from
  `SECRET_KEY`. The database holds the nonce and a keyed hash of the code, so a copy of the database alone reveals
  no code, while the customer's order page can show the current code again.
- **Only the customer sees it**: in `shipments[].delivery_code`, for the order's owner, while the shipment is out for
  delivery. Not the rider, not staff, not the Django admin, not notifications (which only say "open the order page").
- **Expires** after `DELIVERY_OTP_TTL_MINUTES`; **locked** after `DELIVERY_OTP_MAX_ATTEMPTS` wrong codes, after which
  even the right code is refused. A wrong code is counted in a committed transaction although the request fails.
  Six simultaneous wrong guesses are counted one by one (row lock) and cannot exceed the limit.
- **Single use**: the right code completes the delivery in the same transaction; the job is then no longer active and
  accepts nothing. A new code (customer's request, at most one per `DELIVERY_OTP_RESEND_SECONDS`) replaces the old
  one; a failed attempt destroys it.
- Store staff can close a delivery without the code when the customer cannot show it; this needs a note, is flagged
  on the job (`completed_without_otp`) and audit-logged.

**5. Cash on delivery**, `cod.py`. The job stores `cod_amount_due` when it is created: the shipment's share of the
order total (`shipment_amounts`: what was paid for its lines after offers and coupon; the delivery fee travels with
the first shipment; the last takes the rounding remainder, so shares add up to the order total exactly). Completing
the delivery requires the rider to confirm exactly that amount; the number sent by the app is compared, never
stored. Cash stays "in hand" on the rider until store staff record the handover (once; audit-logged); UPI goes to
the store directly. The order's payment record is captured when the whole order is delivered, as before.

**6. Proof of delivery**, `proof.py` + `core/storage.py`. Uploads are opened and verified with Pillow, stripped of
metadata (phones embed GPS position and device model), scaled to at most 1600 px and re-encoded as JPEG under a
random name. They are stored with `PrivateStorage` under `PRIVATE_MEDIA_ROOT`, **outside the web-served media
folder**, and have no URL. Three API views stream them after checking who asks: the rider (own job), the customer
(own order, once delivered) and staff of the shipment's store (each view audit-logged). Responses are
`Cache-Control: private, no-store`.

**7. Privacy between the parties.** The rider sees the customer's name, phone, address and delivery note only while
the job is active, and item names and quantities but no prices. The customer sees the rider's first name and
vehicle, and the phone number only while the rider carries the goods. The rider's free-text failure note goes to the
store, not to the customer.

**8. Locks.** Every function locks **order → assignment → delivery partner**, in that order (also
`assignment.py` and the availability switch), so people acting on the same job wait for each other instead of
deadlocking. Threaded tests: double tap on accept / pickup / deliver (one wins, stock sold once, cash recorded
once), deliver racing with "failed", wrong codes in parallel, the right code racing with a new code, accept racing
with reassignment (never two riders on a shipment), pickup racing with unassign and cancel, two shipments of one
order delivered at the same moment (order delivered once, paid once), cash handover recorded once, going offline
racing with an assignment.

**9. Return pickups.** Staff can send a rider to collect an approved return. The job runs customer → store with the
same steps (no code, no cash). It never changes the return or the order: the store still checks the goods and
receives the return, which restocks and starts the refund. Receiving or rejecting a return closes an open pickup.

**10. Earnings** are calculated on completion: `DELIVERY_EARNING_BASE + DELIVERY_EARNING_PER_KM × distance`
(the store → customer route stored on the shipment); a failed attempt earns `DELIVERY_EARNING_FAILED_ATTEMPT`.

### Background jobs without Celery/Redis
`core.Job` table (built in Phase 8) plus `enqueue(name, payload, dedupe_key=…)`, `@job` handlers and `@periodic`
maintenance tasks, discovered from each app's `jobs.py` (`apps/core/jobs.py`).
- `BACKGROUND_JOBS_MODE=inline` (dev default): a job also runs right after the transaction commits; if it fails it stays
  queued for `run_jobs`.
- `BACKGROUND_JOBS_MODE=cron`: jobs are only queued. Cron runs `python manage.py run_jobs --max-seconds 240` every 5
  minutes: periodic tasks first (payment reconciliation, unpaid-order expiry, refund housekeeping, consistency log),
  then due jobs. Rows are claimed with a conditional `UPDATE … WHERE status='queued'` (portable to SQLite/MySQL/
  PostgreSQL, no `SKIP LOCKED` needed), retried with exponential backoff (30 s … 1 h, 5 attempts), and re-queued if
  a worker died mid-run.
Payment and order state is decided synchronously by checkout verification and webhooks; the jobs are **recovery**
(lost confirmations, abandoned orders, refund submission/polling), so a late cron run only delays them.

## 5. AI architecture

```
apps/ai/services/
  AIService (facade)
   ├── ProductSearchAI          query → structured filters → catalog search
   ├── HardwareAssistant        intent detection + tool calls over catalog tools
   ├── VisionProductIdentifier  image → {category, attributes, confidence} → catalog search
   ├── VoiceShopping            words → spoken.parse → catalogue + quote (or HardwareAssistant) → answer + speech text
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
integrations/vision/  (Phase 14; photo → item name only, see "Photo search")
  VisionProvider.identify(image, kinds) → VisionResult(guesses, calibrated, is_hardware)
   ├── NoVisionProvider      default
   ├── ClipVisionProvider    local CLIP, calibrated probabilities over known kinds
   ├── OllamaVisionProvider  local vision-language model (qwen2.5vl, llava, moondream…)
   └── OpenAICompatibleVisionProvider / AnthropicVisionProvider   optional, owner opts in
```
- **Production:** shared hosting cannot run an LLM (RAM/CPU/process limits). Production defaults to `LLM_PROVIDER=none`,
  so every AI feature still works in a deterministic "basic" mode (keyword search, calculators, spec-rule compatibility,
  co-purchase suggestions). Nothing subscribes to a paid API automatically.
- **Speech:** the browser's Web Speech API listens and `speechSynthesis` speaks (free, client-side); `integrations/speech/`
  (`STTProvider`/`TTSProvider`) adds optional server recognition and voice (Phase 18, "Voice shopping" below).
- **Grounding, enforced in code:** the LLM reaches products only via tools; product cards are built from DB rows; cited IDs
  are re-validated; quantities come from Python formulas and are labelled as estimates; unknown specs give
  `insufficient_information`; the analytics assistant cannot run free-form SQL; low-confidence vision results show "possible matches".
- **Search:** a pluggable backend (`CATALOG_SEARCH_BACKEND`) with one `search(queryset, query) → SearchResult` contract;
  the same ORM code runs on SQLite, PostgreSQL and MySQL (no `pg_trgm`, no vendor full-text). See "Semantic search" below.

### Semantic search (Phase 13)
```
GET /api/products/?q=…, /api/search/suggest/, CatalogRetrievalService (assistant)
  └─ HybridSearchBackend.search                      apps/catalog/semantic/backend.py
       keyword    KeywordSearchBackend (Phase 4) on the customer's words
       related    expand.py: synonym table + assistant vocabulary (en / Devanagari / Hinglish) + typo correction
                  against catalogue words → KeywordSearchBackend.any_terms(catalogue words)
       semantic   index.similarities(query + related words) → cosine against ProductEmbedding vectors
       final      keyword + 0.6 × related + 40 × semantic share  → Case/When `relevance` on the filtered queryset
```
- **Real products only.** Every candidate id is re-filtered through the listing queryset (published, active, not deleted,
  plus the customer's filters); the result is an ordinary annotated queryset, so `ordering`, filters, facets and pagination
  are untouched. Explanations are words ("For “hole”: drill"), never scores.
- **Embedders** (`semantic/embedders.py`, `SEMANTIC_EMBEDDER`): `hashing` (default: character 3–5-grams hashed into 512
  dims; no dependency, works on shared hosting, tolerant of typos and word forms, knows no synonyms), `sentence_transformers`
  (local open-source model, default `paraphrase-multilingual-MiniLM-L12-v2`, 384 dims, English + Hindi meaning; loaded once
  per process in a background warm-up thread started by `config/wsgi.py`; a search during loading uses keywords), `none`.
- **Storage and maths:** `ProductEmbedding` holds float32 bytes per product (portable `BinaryField`, ~1.5 KB at 384 dims),
  the embedder key and a SHA-256 of the embedded text (name, categories, tags, short description). The current embedder's
  vectors are loaded into one matrix (numpy when installed, plain Python otherwise), cached until a row changes; a query is
  one matrix–vector product. 20k products × 384 dims ≈ 30 MB and a few ms per query, so FAISS or pgvector are not needed
  at this size and would tie the code to one database. Swap `index.similarities` if the catalogue grows past that.
- **Freshness:** signals on product/variant/specification queue `catalog.sync_embedding` (deduplicated `core.Job`, inline
  or cron like other jobs); brand/category renames queue an incremental rebuild; unchanged text is never re-embedded.
- **Fallback, in order:** any exception in the extra parts → plain keyword result; embedder off/missing/loading or no index →
  keyword + related words; nothing related and nothing removed → the keyword result unchanged.
- **Tools:** `manage.py rebuild_search_index [--force|--status]`, `manage.py benchmark_search [--set main|held_out]`,
  admin API `/api/admin/search/…`, the dashboard page `/admin/search`, and a Django admin action on products.

### The hardware assistant (Phase 12)
```
POST /api/ai/conversations/{id}/messages/  →  HardwareAssistantService.ask
  IntentService            intent, language (en/hi/hinglish), search words, budget, room size; rules first, model optional
  CatalogRetrievalService  the configured search backend (hybrid since Phase 13; the only place that reads products)
  RecommendationService    message, per-product reasons, budget fit, general knowledge, safety notes, quantity estimates
  AIConversationService    AIConversation / AIMessage records (payload keeps the structured parts)
```
- **Grounding:** the model may help understand and phrase; product ids, prices, stock and delivery come from the database and
  are re-read when a conversation is shown. Products only come from retrieval (a model cannot add one), and a model-written message containing a number that is not in the retrieved products is discarded for the rule-based message.
- **Input:** `HardwareAssistantService.answer(text)` is independent of HTTP and storage; voice questions (Phase 18) call it.
- **Safety:** electrical, gas and structural questions get a "use a qualified professional" note, not step-by-step instructions.
- **Add to cart** goes through the ordinary cart API from the browser; the assistant cannot write prices, stock or orders.
- **Frontend:** `/ai-assistant` (`pages/AssistantPage.tsx`, `features/ai/`): welcome, suggested prompts, product cards,
  Add to Cart / Add recommended items, loading, error with retry, history, clear/delete; full-height with a sticky input on phones.

### Photo search (Phase 14)
```
POST /api/ai/image-search/ (multipart image)            apps/ai/image_views.py → ImageSearchService.search
  Content-Length check   refuse > IMAGE_SEARCH_MAX_BYTES before Django parses the upload (413)
  clean_image            services/image_input.py: size, Pillow open + verify, format JPEG/PNG/WebP (by content, not
                         name), ≤ 40 MP, ≥ 32 px; EXIF rotation applied, alpha flattened, re-drawn as plain RGB pixels
                         (EXIF/GPS/ICC/text gone), scaled to ≤ 1024 px; SHA-256 of the pixels
  VisionProvider         integrations/vision/ (cache: same photo + same model → no second model call)
    none                 default: outcome "unavailable", the page offers the word search
    clip                 local CLIP (sentence-transformers, default clip-ViT-L-14): zero-shot over ~80 hardware kinds +
                         9 "not hardware" kinds + specific catalogue subcategories (services/vision_kinds.py); softmax
                         with CLIP's logit scale → real probabilities; label vectors cached (memory + Django cache)
    ollama               local vision-language model (e.g. qwen2.5vl:3b) answering JSON {item, alternatives,
                         search_terms, confidence, is_hardware}; confidence is the model's own → capped at 0.8
    openai_compatible / anthropic   optional hosted models, same prompt; keys only on the server
  interpret              not_hardware (calibrated "not hardware" mass ≥ 0.4 and above the best tool, or the model says so)
                         · identified (≥ 0.5) · uncertain (up to 3 possibilities ≥ 0.05) · no_match · unavailable
  catalogue              each label's search words → the shop's search backend over published products; kept only when
                         the item's words are whole words in the product (name → "Matches", tags/category → "Related to");
                         a product that is a more specific different item ("Drill *Bit* Set" for "drill") is skipped
  history                signed in: AIConversation(kind=image) + one AIMessage (outcome, refs); never the photo
```
- **Never invents:** the provider sees no prices or stock and can only name things; products come from `selectors.product_queryset()`
  and cards are rebuilt from live rows every time (also when a saved search is reopened).
- **Honest confidence:** percentages are shown as real probabilities only for CLIP; a vision-language model's number is labelled
  "AI estimate", capped, and comes with a "can be wrong" notice. Below 50 % the page says "We're not sure" and calls the
  products "possible matches".
- **Resources:** CLIP ViT-L/14 needs ~1.7 GB disk and ~2 GB RAM, ~1.5 s per photo on a laptop CPU (ViT-B/32: ~600 MB, ~0.2 s,
  noticeably weaker); the model and label vectors are prepared by a background warm-up thread started in `config/wsgi.py`.
  Neither fits shared hosting, so production defaults to `none`.
- **Frontend:** `/image-search` (`pages/ImageSearchPage.tsx`, `features/imageSearch/`), reached from the camera button in the
  search bar: "Take a photo" (`capture="environment"` opens the rear camera on phones), "Choose a photo", drag and drop;
  browser-side type/size checks (HEIC explained) and downscaling to ≤ 1600 px JPEG before upload; result card with
  confidence meter, explanation, alternatives as word-search links, product cards with Add to Cart; word search on every
  dead end; signed-in history (reopen, delete, clear).

### Voice shopping (Phase 18)
```
browser   SpeechRecognition (en-IN / hi-IN)  ─┐    no recognition (Firefox) and server STT on:
                                              │    MediaRecorder → POST /api/ai/voice/transcribe/ → STTProvider
          typed text / example chips ─────────┤        none (default) · faster_whisper (local Whisper) · openai_compatible
                                              ▼
POST /api/ai/voice/command/  {transcript, language, pending[]}      apps/ai/voice_views.py → VoiceShoppingService
  spoken.parse             normalise (Devanagari digits, "50kg" → "50 kg"), read numbers (English words, Hindi 1–100,
                           सौ/हज़ार, डेढ़/ढाई, romanised Hindi, dozen; "do" = 2 only before a unit or product word),
                           units: counting (bags/बोरी/नग/packets/coils/pairs/sets → quantity), measures (kg/m/l → the
                           quantity only if the product is sold that way), sizes (mm, sq mm, inch, grade, W … → search
                           words); loanwords back to English ("सीमेंट" → cement); split "… aur …" when every part has
                           its own quantity; intent: add · set_quantity · confirm · cancel · navigate · search · ask
  catalogue                the listing's own search understanding (interpret: "53 grade" → opt_grade) + search backend
                           over published products; best match + 2 alternatives; variant from the size words said
  pricing                  catalog.quote.quote_product for that quantity (Phase 15 engine: tier, next tier, offers,
                           stock, max per order); "confirm" re-prices the pending ids from the database
  answer                   sentences in en / hi / hinglish + `speech` (₹ → "rupees"/"रुपये"); ask → HardwareAssistant
  history                  signed in: AIConversation(kind=voice), the words only
browser   shows lines; on "yes"/tap → POST /api/cart/items/ per line (prices again); speechSynthesis reads `speech`
          (server TTS only if switched on and the device has no voice); navigate → React Router
```
- **Never buys by voice:** the command API has no cart or order write; a proposal needs "yes"/"haan" or a tap and the
  browser adds through the normal cart API. "Checkout" only opens the page; the customer places and pays there.
- **Prices from the engine only:** the client sends product/variant ids and quantities, never prices; a confirmation is
  priced again, so a price change between the proposal and "yes" is honoured.
- **Privacy:** with the default, Chrome's speech service hears the voice and the shop receives only the words (the page
  says so). A server recording is checked by its bytes, transcribed and dropped. Throttles `voice` and `voice_audio`.
- **Resources:** nothing extra by default. Whisper `small` via faster-whisper (CTranslate2 int8, no PyTorch) is ~480 MB on
  disk, ~1 GB RAM, ~3 s per short command on a laptop CPU, loaded on first use: a VPS option, not shared hosting.
- **Frontend:** `/voice` (`pages/VoicePage.tsx`, `features/voice/`), microphone in the search bar, mobile menu, footer
  and home page: language choice (remembered), microphone with live words, "Read answers aloud" (remembered), type
  box and examples, priced line cards (bulk tier, "Add 20 more for ₹389 each (make it 30)", alternatives, problems),
  Add / Add all / Cancel, search results, assistant answers, signed-in history (delete, clear).

## 6. Integrations (provider pattern)

| Concern   | Default (free)                         | Optional production provider     | Switch |
|-----------|----------------------------------------|----------------------------------|--------|
| Payments  | `MockPaymentProvider` (dev only; prod refuses it) + COD | Razorpay (UPI, cards, net banking, refunds, webhooks) | `PAYMENT_PROVIDER` |
| WhatsApp  | `MockWhatsAppProvider` (stores and logs messages)  | WhatsApp Business Cloud API (Meta) | `WHATSAPP_PROVIDER` |
| SMS       | `MockSMSProvider`                      | MSG91 / Twilio                   | `SMS_PROVIDER` |
| Email     | console backend (dev)                  | hosting mailbox SMTP             | `EMAIL_*` |
| Maps      | Offline: haversine distance, admin-managed PIN centres. OpenStreetMap tiles + **Leaflet** for the address pin (frontend) | Still free: Nominatim geocoding (rate-limited, cached), OSRM routing (self-hosted or the public demo server). No paid maps provider is implemented | `GEOCODING_PROVIDER`, `ROUTING_PROVIDER`, `VITE_MAP_TILE_URL` |
| LLM       | `NoLLMProvider` / Ollama (local)       | OpenAI-compatible / Anthropic    | `LLM_PROVIDER` |
| Speech    | the browser (Web Speech API, `speechSynthesis`) | local Whisper (faster-whisper) / OpenAI-compatible audio API | `SPEECH_STT_PROVIDER`, `SPEECH_TTS_PROVIDER` |
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
- Proof-of-delivery photos are private files (Phase 10): stored outside the web root, re-encoded without metadata,
  served only by authenticated API views. Delivery codes are never stored and are shown to the order's owner only.
- Delivery partners can act only on their own jobs, through fixed actions; they have no access to orders, prices,
  customers, inventory or staff endpoints.
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
  (`CATALOG_SEARCH_BACKEND`); Phase 13 switched the default to hybrid search with no change to these calls. The UI only
  adds what the optional fields allow: a "we searched for what you probably mean" notice (`matched = related`) and a
  short reason under products found by related words or meaning (also in the type-ahead). "Ask AI" in the header is a
  clearly labelled "coming soon" entry point, not a fake assistant.
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

### Delivery UI (Phase 9)
`features/delivery`: typed quotes, hooks (`useServiceability`, `useProductEstimate`, `useCartEstimate`) and the shared
display components. The browser never calculates a time or a fee; it shows what the fulfilment engine returned.
- **One PIN code per browser** (`location.ts`, `useSyncExternalStore` over `localStorage`), shared by the header
  selector, product pages and the cart. The header selector checks the PIN with `/delivery/check/`.
- `DeliveryEstimate` renders a quote the same way everywhere: "⚡ Fast delivery available · Estimated delivery:
  42 minutes", or "🚚 Standard delivery · Estimated delivery: Tomorrow, 10:00 AM – 12:00 PM" preceded by "Fast delivery
  unavailable — *reason*", or the reason the items can't be delivered (`role="alert"`). Several stores are listed one
  per line. Emoji are decorative (`aria-hidden`); the words carry the meaning.
- **Product page**: estimate for the selected variant and quantity to the saved PIN; without a PIN, only the catalogue
  hint and a PIN form (nothing promised). **Cart**: estimate to the default saved address, else the PIN.
  **Checkout**: the plan for the chosen address with the zone's fee; an out-of-zone address blocks the order.
  **Confirmation, order detail**: `OrderDeliveryCard` (type, estimate, window, preparation time, fulfilment store,
  delivery status, one block per store for split orders). **Order history**: the delivery sentence per order.
- **Address map pin** (`features/addresses/AddressLocationField` + `MapPinPicker`): optional; tap the map, drag the
  pin or use the browser's location. Leaflet and its CSS load only when the map is opened (separate ≈ 150 kB chunk).
  Tiles come from `VITE_MAP_TILE_URL` (OpenStreetMap by default, see FREE_TOOLS.md for its usage policy).
- If an estimate can't be loaded the page still works: the product page falls back to the PIN form, the cart hides
  the block, and checkout (which needs the plan) shows its normal retry.
- Main bundle measured at the Phase 9 build: 481 kB (148 kB gzipped).

### Delivery tracking and the rider app (Phase 10)
- **Customer** (`features/delivery/tracking.tsx`, on the order page and the confirmation page): one block per
  shipment with its steps, the rider's name and vehicle, a call link while the rider carries the goods, the cash to
  pay, the delivery code in large digits (read out digit by digit to screen readers) with its validity and a
  "Get a new code" button, the failure reason and next step, and after delivery who received it and the photo. The
  photo is fetched only when asked for, with the session token, and shown from memory (`fetchPrivateImage`).
  Orders on the move are refetched every 20 s (`useOrder(number, 'tracking')`); finished orders are not polled.
- **Rider app** (`/rider`, `/rider/jobs/:id`, `/rider/history`; `features/rider`, `pages/RiderPages.tsx`,
  `RiderLayout`): a separate plain shell with large touch targets. Dashboard (availability switch, active jobs,
  earnings, cash to hand over), job page (what to do next, the one button for the next step, store and customer
  cards with "Navigate" (`geo:` link to the phone's maps app), "Open map" (OpenStreetMap) and "Call" links, items,
  delivery note, history) and delivery history. The handover form takes the customer's code, the cash confirmation
  for COD, who received it and the photo. The app shows buttons from the server's `next_actions` and shows the
  server's reason when a step is refused; it never decides a status itself.
- Delivery partners who log in land on `/rider`; the account menu links to it. Everyone else is told the area is for
  delivery partners (and the API refuses them). The rider pages are a lazy chunk (≈ 29 kB), not part of the shop.
- Active job lists refresh every 30 s, so a new job appears without reloading. The rider's position is sent with
  pickup/start/complete only when the browser already has permission; it never blocks a step.
- Staff worked through the staff API and the Django admin until Phase 11 added the dashboard below.
- Main bundle measured at the Phase 10 build: 484 kB (149 kB gzipped).

### Business dashboard (Phase 11)
- **Where.** `/admin/*` in the React app (`app/layouts/AdminLayout.tsx`, `pages/admin/*`, `features/admin/*`).
  Django's admin moved to `/django-admin/` in Phase 1 for this reason; it stays available for rare tasks (e.g. site
  configuration) but daily operations no longer need it.
- **Who.** `AdminLayout` lets administrators and store managers in, tells customers and delivery partners the area is
  not for them, and asks visitors to sign in. It then loads `GET /api/admin/session/`, which says which sections the
  role may open (the menu is built from it) and which stores the person works with. Hiding a menu entry or a button is
  a convenience: **every request is checked again by the API** (`IsStaffRole`, `IsAdminRole`, the new
  `IsAdminOrStaffReadOnly`, and `dashboard/scope.py` which narrows every list to a manager's stores and turns a
  request for another store into 404).
- **Backend.** A new app `apps/dashboard` with **no models**: it reads and reuses the existing services (catalogue
  `save_product`, inventory `apply_movement`, orders `transition_order`, the Phase 10 assignment and workflow modules,
  returns and refunds services, `accounts.admin_services.update_user`, support `post_message`). Modules: `scope.py`
  (store scoping, date ranges), `metrics.py` (dashboard summary and analytics), `orders.py`, `catalog.py`,
  `stores.py`, `offers.py`, `people.py` (customers, riders, jobs, support), `views.py` (session/summary/analytics).
  Offers and coupons are stored here but priced only by the Phase 6 engine at checkout; refund amounts come from the
  Phase 7 returns service; stock changes only through the Phase 2 ledger. Nothing is calculated twice.
- **Numbers.** `metrics.py` aggregates with the ORM at request time; nothing is sampled, cached or estimated. Days,
  weeks and months are bucketed in Python from a narrow `values_list`, not with database date functions, because
  time-zone-aware truncation needs time-zone tables on MySQL that shared hosting often lacks. Periods are capped at
  366 days. Definitions (also in the UI): orders count by the local day they were placed; revenue = paid orders;
  refunded = processed refunds by the day they were paid back; net = revenue − refunded; on time = delivered within
  the window promised at checkout.
- **Frontend.** Sidebar + top bar (quick order search, "To do" list from the summary's `attention` items, sign-out),
  a drawer menu on phones, breadcrumbs, and shared primitives in `features/admin/ui.tsx`: a `DataTable` that is a
  real table on desktop and one card per row on phones (one DOM, CSS only), `ListView` (loading / error / empty /
  paginated), URL-backed filters (`useListParams`: bookmarkable, back button works, search only on submit),
  `ConfirmDialog` for anything that touches money, stock, access or what customers see, `FormDialog`, badges.
  Server errors are shown in the dialog that caused them, so the person can correct and retry.
- **Bundles.** The dashboard shell and each section are separate lazy chunks (7–26 kB each); the customer bundle is
  unchanged (488 kB / 150 kB gzipped at this build). Recharts (MIT) is in its own 408 kB chunk, fetched the first
  time a chart is shown, through a plain dynamic import rather than `React.lazy` so a slow chart download never holds
  back a filter change. Every chart is `aria-hidden` and paired with the same numbers as a table.
- **Not built (see TASKS.md):** live push (lists refresh every 60 s while open), a map editor for zone polygons,
  bulk product import, settlement reports, and a change log screen for the audit trail.

### Storefront (Phase 16)
- **One source for every number.** Prices, tiers, offers, free delivery and COD come from the Phase 15 engine
  (`quote`, cart, checkout); delivery from the Phase 9 engine. The browser formats and never computes a price.
- **PIN-aware browsing.** `apps/delivery/pin.py` turns a PIN into a `PinContext` (serving stores, stores that can
  deliver fast *now*, the best zone, the engine's message), computed like `/delivery/check/` and cached 60 s per PIN.
  `catalog.selectors.annotate_pin` adds `pin_stock`/`pin_fast_stock` subqueries to the listing query, so a page of
  cards stays one query. The frontend adds the saved PIN to every catalogue request (`usePinParams`), so cards, rails,
  facets, product pages, quotes and curated lists all change together when the PIN changes.
- **Search understanding.** `catalog/interpret.py` matches the query against the catalogue's own vocabulary (option
  values, spec values with units, category names; cached 5 min) and the listing applies the matches as normal filters
  only when results remain. The search backend (Phase 13) still ranks the results.
- **Pages.** Home (eager, sections from categories, collections, listing rails, offers, recently viewed); product,
  category, search and brand pages are lazy chunks. `ProductBrowser` (URL-backed filters, facets, chips, drawer,
  pagination) serves search, all products, categories and brands. `usePageMeta` sets title, description, canonical,
  Open Graph and JSON-LD.
- **Recently viewed** is a `useSyncExternalStore` over localStorage (slugs only); products are fetched fresh.

### Loyalty credits (Phase 17)
- **Ledger, not balances.** `apps/loyalty/ledger.py` is the only writer. Credits are lots with their own expiry;
  every use or expiry is a debit allocated to lots (oldest expiry first, rows locked with `select_for_update`), so the
  same credit can't be spent twice and a lot can't go below zero. Balance and wallet totals are sums over entries.
- **Pricing.** `orders.pricing.price_lines(..., use_credits=True)` prices once without credits, asks
  `ledger.credit_quote` for the cap (share × goods after offers and coupon, ≤ spendable) and prices again with that
  amount as the last discount layer (spread pro rata like the coupon; GST on what is paid; the delivery decision is
  made before credits). Checkout preview and `place_order` share this path; `place_order` then redeems the same
  amount inside the order transaction and records pending cashback (`cashback_for` on `paid_by_line`).
- **Lifecycle hooks.** `orders.services._apply_transition` calls `on_order_cancelled` (reverse waiting credits, restore
  used credits with original expiry) and `on_order_delivered` (pending → eligible with `available_at` = delivery +
  return window; referral rewards). `orders.returns.receive_return` calls `on_return_received` with the credit share
  of the returned units and the paid amount refunded (`paid_amounts` excludes credits, so refunds pay back money only).
- **Jobs.** `loyalty.release_credits` and `loyalty.expire_credits` run in `manage.py run_jobs` (cron). Both are
  idempotent and safe to run concurrently (status-guarded updates / row locks).

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
