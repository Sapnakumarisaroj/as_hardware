# Roadmap

Each phase ends with passing tests, lint and type checks, and a build, and the app stays runnable. A phase is marked done only after verification.
Every phase respects the hosting constraints in `ARCHITECTURE.md` §1: portable DB, no Redis/Celery/Docker in production, and free/mock providers by default.

| # | Phase | Key deliverables | Exit criteria |
|---|---|---|---|
| 1 ✅ | Setup & architecture | docs (incl. DEPLOYMENT), Django project with env-driven split settings, vendor-portable DB config (PostgreSQL/MySQL/SQLite), DRF + JWT libs + OpenAPI, core app (base models, soft delete, health, error envelope, request ID, audit log), custom User, Passenger entry point, React/Vite/TS/Tailwind shell, Router, Query, Axios, `.htaccess`, optional compose | backend tests + ruff + `check --deploy`; frontend lint/typecheck/test/build; health endpoint live |
| 2 ✅ | Database + backend | all domain models (portable), services, core APIs (catalog, addresses, cart, wishlist, orders, inventory), admin, `seed_demo_data` (refuses without DEBUG) | 85 tests, lint, checks, migrations on SQLite; production-vendor run pending hosting info |
| 3 ✅ | Auth + roles | register/login/logout/refresh/forgot/reset, profile, addresses, role permissions, throttles | auth API tests |
| 4 ✅ | Catalog + search (delivered with the customer catalogue UI) | category tree, products/variants/specs/images, filters/sorting, portable keyword `SearchBackend`, suggestions | search tests on the SQLite path |
| 5 ✅ | Checkout + orders UI (delivered: cart, checkout, addresses, COD + mock payment, order history/detail/cancel) | originally "customer frontend"; the Leaflet/OSM pin picker moves to Phase 9 | component + API tests |
| 6 ✅ | Cart, wishlist, checkout: offer engine | server cart, wishlist and checkout preview (done in 2/5) + automatic offers, offer/coupon stacking, coupon discovery | cart/coupon/offer tests |
| 7 ✅ | Orders + inventory: returns, reorder, concurrency | `place_order`, reservations, state machine, history and cancel already existed (2/5). Added: returns (request/approve/reject/receive, restock, pending refund, partial returns), "Buy again", threaded concurrency tests, full transition matrix | concurrency + transition tests |
| 8 ✅ | Payments + refunds | Razorpay provider (order, signature verify + server fetch, capture, webhooks, idempotent refunds, refund status) over stdlib HTTP; mock kept for dev/tests; webhook idempotency; late/duplicate/mismatched money auto-refunded; refund processing incl. return refunds and manual COD refunds; reconciliation, unpaid-order expiry, consistency checks; `core.Job` queue + `run_jobs` cron command; COD cash recorded at delivery | signature/webhook/idempotency/refund/security tests; live flows (mock gateway) |
| 9 | Stores + delivery engine | stores/zones, fulfillment selection, ETA engine (haversine), Nominatim geocode cache | ETA unit tests |
| 10 | Delivery partner app | availability, assignments, pickup, OTP, proof upload, earnings, OSM navigation links | flow tests |
| 11 | Admin dashboard | KPIs, CRUD screens, order ops, inventory, coupons, customers | permission tests |
| 12 | AI hardware assistant | `LLMProvider` (none / Ollama / OpenAI-compatible / Anthropic), tool calling over catalog, basic mode without an LLM | grounding tests |
| 13 | Semantic search | embeddings (JSON vectors, in-Python cosine), hybrid ranking; enabled only if an embedding provider is set | relevance tests |
| 14 | Image identification | vision via provider (Ollama llava locally), confidence handling | fixture tests |
| 15 | Voice shopping | browser Web Speech API STT, server STT/TTS interface, English/Hindi/Hinglish | pipeline tests |
| 16 | Project builder | guided flows, kits from catalog | flow tests |
| 17 | Quantity calculators | deterministic formulas, estimate labels | formula tests |
| 18 | Compatibility checker | spec rule engine, verdicts | rule tests |
| 19 | Smart cart, recommendations, budget, bundles, review summary | privacy controls, admin bundle approval | tests |
| 20 | WhatsApp + notifications | `MockWhatsAppProvider`, optional WhatsApp Cloud API, SMTP email, in-app | signature tests |
| 21 | Analytics + business assistant | whitelisted queries, charts | tests vs. fixtures |
| 22 | Security hardening | deploy checks, audit coverage, upload hardening, rate limits | `check --deploy` clean |
| 23 | Testing | coverage gaps, Playwright e2e for critical flows, MySQL test run | e2e green |
| 24 | Deployment to existing hosting | final DEPLOYMENT.md for the confirmed host, deploy scripts (zip/rsync/Git), backups, runbook | live on the owner's domain |

## Open decisions for the owner
1. **Hosting details**: see DEPLOYMENT.md §0. This blocks only Phase 24; building continues meanwhile.
2. Final brand name (currently "BoltRun", configurable).
3. Production AI provider: stays `none` (basic mode) until you choose one. Nothing is subscribed automatically.
4. Razorpay and WhatsApp Business accounts: needed only when going live with those channels.
