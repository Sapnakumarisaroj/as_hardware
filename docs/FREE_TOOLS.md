# Free & Open-Source Tools

Policy: only free/open-source tools, with no paid SaaS, cloud or AI API unless the owner explicitly approves it.
Every external service has a free mock/local default. Exact versions are pinned in `backend/requirements/*.txt`
and `frontend/package-lock.json`.

## Backend (Python) — runtime (`requirements/base.txt`)
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Web framework, ORM, admin, migrations | Django 5.2 LTS | ✅ BSD-3 | ✅ | No | LTS, security support until April 2028 |
| REST APIs, serializers, permissions, throttling | Django REST Framework | ✅ BSD-3 | ✅ | No | |
| JWT authentication (access + rotating refresh, blacklist) | djangorestframework-simplejwt | ✅ MIT | ✅ | No | Signing key = `DJANGO_SECRET_KEY` unless `JWT_SIGNING_KEY` is set |
| OpenAPI schema, Swagger UI, ReDoc | drf-spectacular | ✅ BSD-3 | ✅ | No | `/api/docs/`, `/api/redoc/` |
| CORS allow-list | django-cors-headers | ✅ MIT | ✅ | No | |
| `.env` / environment config | django-environ | ✅ MIT | ✅ | No | |
| PostgreSQL driver | psycopg 3 (binary) | ✅ LGPL-3.0 | ✅ | No | Used only if `DATABASE_URL=postgres://…` |
| Password hashing | argon2-cffi | ✅ MIT | ✅ | No | Argon2id; PBKDF2 fallback built into Django |
| Static files from the Python app (shared hosting friendly) | WhiteNoise | ✅ MIT | ✅ | No | No separate static server needed |
| Image validation for product/delivery-proof uploads | **Pillow** *(new in Phase 2)* | ✅ MIT-CMU (HPND) | ✅ | No | Needed by Django `ImageField`; prebuilt wheels, no compiler on hosting |

## Backend — optional / environment-specific
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| MySQL/MariaDB driver | PyMySQL (`requirements/mysql.txt`) | ✅ MIT | ✅ | No | Pure Python; for MySQL-only shared hosting |
| Production WSGI server (VPS only) | gunicorn (`requirements/prod.txt`) | ✅ MIT | ✅ | No | Shared hosting uses Passenger via `passenger_wsgi.py` instead |
| Local database | SQLite (bundled with Python) | ✅ Public domain | ✅ | No | Default when `DATABASE_URL` is blank |

## Backend — development & testing (`requirements/dev.txt`)
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Test runner | pytest | ✅ MIT | ✅ | No | |
| Django test integration | pytest-django | ✅ BSD-3 | ✅ | No | |
| Coverage | pytest-cov | ✅ MIT | ✅ | No | |
| Lint + formatter | Ruff | ✅ MIT | ✅ | No | `ruff check .`, `ruff format .` |
| Test data builders | `apps/core/testing.py` (in-repo) | ✅ project code | ✅ | No | No factory library needed |

## Catalog & search (Phase 4): no new dependencies
| Feature | Tool | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Product search | In-repo `KeywordSearchBackend` (Django ORM) | ✅ project code | ✅ | No | Portable across SQLite/PostgreSQL/MySQL; replaceable by a semantic backend (Phase 13) via `CATALOG_SEARCH_BACKEND` |
| Filters / facets | Django ORM aggregates | ✅ | ✅ | No | |
| Product images | Django storage + local `MEDIA_ROOT` | ✅ | ✅ | No | S3/Cloudinary possible later via `STORAGES`; not used now |
| Demo images | Pillow (already a dependency for `ImageField`) | ✅ HPND | ✅ | No | Drawn locally by `seed_demo_data`; dev only |
| Icons | Inline SVG components (`components/icons.tsx`) | ✅ project code | ✅ | No | No icon font/CDN |

## Checkout & orders (Phase 5): no new dependencies
| Feature | Tool | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Online payments (dev) | In-repo `MockPaymentProvider` (HMAC-signed intents) | ✅ project code | ✅ | No | Simulates success / failure / cancellation; moves no money; blocked in production |
| Cash on delivery | In-repo | ✅ | ✅ | No | Works without any gateway |
| Order notifications | Django `Notification` rows (in-app) + `django.core.mail` | ✅ | ✅ | No | Console email backend in dev; the hosting SMTP mailbox in prod |
| Idempotency / locking | Database unique constraint + `select_for_update` | ✅ | ✅ | No | No Redis or queue needed |
| Idempotency keys (browser) | `crypto.randomUUID()` | ✅ built into browsers | ✅ | No | |

## Offers & coupon discovery (Phase 6): no new dependencies
The offer engine is plain Python/`Decimal` over Django ORM reads (`apps/offers/engine.py`); offers are managed in the
free Django admin. No promotion/pricing SaaS, no Redis cache.

## Payments, refunds & jobs (Phase 8): no new dependencies
| Feature | Tool | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Gateway HTTP client | Python `urllib.request` + `json` | ✅ PSF | ✅ | No | Replaces the Razorpay SDK (which would pull in `requests`) |
| Checkout/webhook signatures | Python `hmac` + `hashlib` (SHA-256, constant-time compare) | ✅ PSF | ✅ | No | |
| Background jobs | In-repo `core.Job` queue + `manage.py run_jobs` via the hosting's **cron** | ✅ project code | ✅ | No | No Redis/Celery; portable claim with a conditional UPDATE |
| Tests for the gateway | Recorded fakes of Razorpay's REST API + `unittest.mock` | ✅ | ✅ | No | Runs without network or credentials |

## Frontend (no new packages in Phases 4–8)
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| UI library | React 19 | ✅ MIT | ✅ | No | |
| Routing | React Router | ✅ MIT | ✅ | No | |
| Server state / caching | TanStack Query | ✅ MIT | ✅ | No | |
| HTTP client | Axios | ✅ MIT | ✅ | No | |
| Build tool / dev server | Vite (+ @vitejs/plugin-react) | ✅ MIT | ✅ | No | Builds static files; no Node.js needed on the server |
| Type checking | TypeScript | ✅ Apache-2.0 | ✅ | No | |
| Styling | Tailwind CSS 4 (+ @tailwindcss/vite) | ✅ MIT | ✅ | No | |
| Lint | ESLint, typescript-eslint, react-hooks & react-refresh plugins, globals | ✅ MIT | ✅ | No | |
| Tests | Vitest, jsdom, Testing Library (react, jest-dom, user-event) | ✅ MIT | ✅ | No | |

## Tooling on the dev machine
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Python runtime | CPython 3.11 | ✅ PSF | ✅ | No | |
| JavaScript runtime | Node.js 24 LTS (portable zip) | ✅ MIT | ✅ | No | In `%LOCALAPPDATA%\tools`, not on system PATH |
| Version control | Git | ✅ GPL-2.0 | ✅ | No | |
| Containers (optional, local only) | Docker Desktop | ⚠️ Free for personal use, education, and small businesses (< 250 employees **and** < $10M revenue); larger companies need a paid subscription | ✅ | No | **Not required.** The project runs without it; production never uses it |

## Integrations — defaults vs. optional production providers
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Payments (dev) | `MockPaymentProvider` (in-repo, `integrations/payments/mock.py`) | ✅ project code | ✅ | No | Moves no money; HMAC-signed intents and webhooks, instant refunds; **blocked in production** |
| Payments (prod, optional) | Razorpay (via `integrations/payments/razorpay.py`) | ❌ Commercial gateway: no subscription; a per-transaction fee only on live payments. Test mode (`rzp_test_…` keys) is free | ❌ | Yes | Implemented in Phase 8 with Python's standard library (`urllib`, `hmac`), **no SDK or new dependency**. Optional; COD works without it. Not activated: needs the owner's Razorpay account and keys |
| Razorpay Checkout script | `checkout.razorpay.com/v1/checkout.js` | ❌ Razorpay's hosted script (free to load) | ❌ | Public key id only | Loaded only on the payment page when an attempt is a Razorpay one; card/UPI entry happens inside Razorpay's window, never on our pages |
| WhatsApp (dev) | `MockWhatsAppProvider` (Phase 20) | ✅ project code | ✅ | No | Records messages; never claims real delivery |
| WhatsApp (prod, optional) | WhatsApp Business Cloud API (Meta) | ❌ Meta pricing per conversation/template | ❌ | Yes | Needs owner approval + Meta business account |
| Maps (planned) | OpenStreetMap tiles + Leaflet; Nominatim geocoding | ✅ ODbL data / BSD-2 library | ✅ | No | Respect Nominatim policy (≤ 1 req/s, cache results, identify User-Agent) |
| Distance / ETA (planned) | Haversine (in-repo Python) | ✅ | ✅ | No | Routing APIs are optional later |
| AI (dev, planned) | Ollama + open models (e.g. Llama 3.1, Qwen 2.5, LLaVA) | ✅ MIT runtime; model licences vary | ✅ | No | Needs local RAM/GPU; not usable on shared hosting |
| AI (prod default) | `none` provider: rule-based fallbacks | ✅ project code | ✅ | No | No paid AI API is subscribed automatically |
| Email (prod) | SMTP mailbox from the hosting plan | ✅ included in hosting | ❌ | SMTP password | Console backend in dev |
| SMS (prod, optional) | MSG91 / Twilio | ❌ paid per message | ❌ | Yes | Mock provider until approved |

## Deliberately NOT used
Redis, Celery, RabbitMQ, Elasticsearch/OpenSearch, pgvector-only features, paid vector databases, AWS/Azure/GCP services,
Sentry SaaS, and any paid AI API. They are replaced by DB-backed queues + cron, DB cache, portable SQL search, and in-Python vector math.
