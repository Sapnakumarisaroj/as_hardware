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
| Product search | In-repo `KeywordSearchBackend` (Django ORM) | ✅ project code | ✅ | No | Portable across SQLite/PostgreSQL/MySQL; since Phase 13 the fallback underneath `HybridSearchBackend` (see "Semantic search") |
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

## Fulfilment, delivery zones & ETA (Phase 9)
No paid maps or routing service is used or implemented (no Google Maps). The default configuration makes **no
network calls at all**.

| Feature | Tool | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Distance | Haversine formula (in-repo Python, `integrations/maps/base.py`) × `ROAD_DISTANCE_FACTOR` | ✅ project code | ✅ | No | **Default** (`ROUTING_PROVIDER=haversine`). No limits |
| Zone polygons | Ray-casting point-in-polygon (in-repo Python) | ✅ project code | ✅ | No | No GIS extension (PostGIS etc.) needed, so it runs on shared MySQL hosting |
| PIN code centres | `delivery_pincode` table, managed in Django admin | ✅ project data | ✅ | No | Demo seed has approximate centres for 11 Pune PIN codes |
| Road routing (optional) | **OSRM** `/route/v1/driving` via Python `urllib` | ✅ BSD-2 software, ODbL data | ✅ if self-hosted | No | `ROUTING_PROVIDER=osrm`. See limits below |
| Geocoding (optional) | **Nominatim** (OpenStreetMap) via Python `urllib` | ✅ GPL-2 software, ODbL data | ✅ if self-hosted | No | `GEOCODING_PROVIDER=nominatim`. See limits below |
| Address map pin | **Leaflet 1.9** (npm `leaflet`, types `@types/leaflet`) | ✅ BSD-2 | ✅ | No | The only new package of Phase 9. Loaded lazily (own ≈ 150 kB chunk) when a customer opens the map |
| Map tiles | **OpenStreetMap** standard tiles (`tile.openstreetmap.org`) | ✅ ODbL data; free to use within the tile policy | ❌ | No | `VITE_MAP_TILE_URL`. See limits below |
| Browser location | W3C Geolocation API | ✅ built into browsers | ✅ | No | Needs HTTPS in production and the customer's permission |

### Usage limits of the public OpenStreetMap services
These are community-funded servers with **no SLA**. They are fine for development and light use; a busy store should
self-host or use a provider that offers the same software (both are configuration changes, not code changes).

| Service | Limit / policy | How the project complies |
|---|---|---|
| Nominatim (`nominatim.openstreetmap.org`) | At most **1 request per second**; an identifying `User-Agent` (set `NOMINATIM_USER_AGENT` to the site name and a contact email); results **must be cached**; no bulk or systematic geocoding; no autocomplete | One request per second per process (lock + sleep); every answer, including "not found", is stored in `delivery_geocodecache` and never asked again; used only for a saved address without a map pin and for unknown PIN codes; the map pin avoids geocoding altogether |
| OSRM demo server (`router.project-osrm.org`) | Demo server for **light, non-commercial-scale use**: about **1 request per second**, no heavy or commercial load, may be slow or offline at any time | Routes are cached for 24 h (`ROUTE_CACHE_SECONDS`); 4 s timeout; any error falls back to the offline haversine estimate; for production traffic set `OSRM_BASE_URL` to a self-hosted OSRM (free software, needs a VPS and a map extract) |
| OSM tile server (`tile.openstreetmap.org`) | No bulk downloading or prefetching; keep the visible "© OpenStreetMap contributors" attribution; a valid `Referer` (browsers send it); heavy users must switch to another tile source | Tiles load only while a customer has the address map open; attribution is shown on the map; `VITE_MAP_TILE_URL` switches to any other tile server |

## Delivery partner workflow (Phase 10): no new dependencies
No SMS gateway, no paid maps, no file-storage service and no new package (backend or frontend).

| Feature | Tool | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Delivery code (OTP) | Python `hmac`, `hashlib`, `secrets` | ✅ PSF | ✅ | No | Shown on the customer's order page instead of being sent by SMS, so no SMS provider is needed. SMS/WhatsApp delivery of the code can be added in Phase 23 |
| Proof-of-delivery photos | Pillow (already a dependency) + Django `FileSystemStorage` on the hosting disk | ✅ HPND / BSD | ✅ | No | Re-encoded without metadata; stored under `PRIVATE_MEDIA_ROOT`, outside the web root. Uses hosting disk space (about 150–400 kB per photo) |
| Rider navigation | `geo:` links (open the phone's own maps app) and openstreetmap.org links | ✅ open standard / ODbL | n/a | No | Plain links opened by the rider; nothing is embedded and no quota applies to the project |
| Rider position | W3C Geolocation API in the browser | ✅ built into browsers | ✅ | No | Optional; needs HTTPS and the rider's permission |
| Camera | `<input type="file" capture>` | ✅ web standard | ✅ | No | Opens the phone camera from the browser; no native app needed |
| Rider app | The existing React SPA (`/rider`) | ✅ | ✅ | No | A web page, not an app-store app: nothing to publish or pay for |

## Business dashboard (Phase 11): one new frontend package
No analytics service, no BI tool, no admin-panel product and no paid chart library. The dashboard is part of the
existing React app and reads the project's own database through the Django API.

| Feature | Tool | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Charts | **Recharts 3** (React + D3 internals) | ✅ MIT | ✅ | No | Added in Phase 11. Loaded only on the dashboard and analytics pages (own 408 kB chunk, 115 kB gzipped); customers never download it. Every chart has the same numbers as an accessible table |
| Statistics | Django ORM aggregation + Python bucketing | ✅ BSD / PSF | ✅ | No | No analytics database, no cron pre-aggregation; portable across PostgreSQL / MySQL / SQLite |
| Dashboard UI | The existing React SPA (`/admin`) | ✅ | ✅ | No | Replaces day-to-day use of the Django admin (`/django-admin/` stays for rare tasks) |

## Frontend (no new runtime packages in Phases 4–8; Leaflet added in Phase 9; none in Phase 10; Recharts in Phase 11)
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Charts | Recharts 3 | ✅ MIT | ✅ | No | Dashboard/analytics only (lazy chunk) |
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
| WhatsApp (dev) | `MockWhatsAppProvider` (Phase 23) | ✅ project code | ✅ | No | Records messages; never claims real delivery |
| WhatsApp (prod, optional) | WhatsApp Business Cloud API (Meta) | ❌ Meta pricing per conversation/template | ❌ | Yes | Needs owner approval + Meta business account |
| Maps, distance, ETA | Haversine + PIN table (default); Leaflet + OpenStreetMap tiles; optional Nominatim and OSRM | ✅ | ✅ (default) | No | Built in Phase 9: see "Fulfilment, delivery zones & ETA" above for the usage limits |
| AI (dev, Phase 12) | Ollama + **`qwen2.5:3b`** (about 1.9 GB download; Qwen 2.5 3B is small enough for a laptop CPU) | ✅ MIT runtime; model licence per Qwen | ✅ | No | See "AI assistant" below. Needs roughly 4 GB free RAM; not usable on shared hosting |
| AI (prod default) | `none` provider: rule-based fallbacks | ✅ project code | ✅ | No | No paid AI API is subscribed automatically |
| Email (prod) | SMTP mailbox from the hosting plan | ✅ included in hosting | ❌ | SMTP password | Console backend in dev |
| SMS (prod, optional) | MSG91 / Twilio | ❌ paid per message | ❌ | Yes | Mock provider until approved |

## AI assistant (Phase 12)
- **Chosen local model:** `qwen2.5:3b` through Ollama (multilingual, so it copes with Hindi and Hinglish). Setup:
  install Ollama, `ollama pull qwen2.5:3b`, then set `LLM_PROVIDER=ollama` and `LLM_MODEL=qwen2.5:3b` in `backend/.env`
  (`OLLAMA_BASE_URL` defaults to `http://localhost:11434`; `LLM_TIMEOUT_SECONDS` defaults to 45).
- **Minimum:** about 4 GB free RAM and a few GB of disk; a GPU is optional (CPU answers take several seconds).
- **Fallback:** with `LLM_PROVIDER=none` (the default, and the production default), or when the model is down or slow, the
  assistant answers in *basic mode* (rule-based understanding + the catalogue search, hybrid since Phase 13, still from real products). If a
  configured model fails the customer sees "AI is temporarily unavailable. You can search products normally."
- **Optional providers, never enabled automatically:** `openai_compatible` (any compatible endpoint: `OPENAI_COMPATIBLE_BASE_URL`,
  `OPENAI_COMPATIBLE_API_KEY`) and `anthropic` (`ANTHROPIC_API_KEY`). Keys stay on the server; the browser never sees them.

## Semantic search (Phase 13)
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Hybrid ranking, synonyms, Hindi/Hinglish, typo correction | In-repo `apps/catalog/semantic/` (Python `difflib`, `hashlib`, `zlib`, `array`) | ✅ project code | ✅ | No | **Default.** No new dependency; works on shared hosting and every database |
| Default embedder | In-repo `hashing` embedder (character n-grams → 512 numbers) | ✅ project code | ✅ | No | No download, no model. Typo- and word-form tolerant; knows no synonyms (the tables cover those) |
| Optional embedder | [sentence-transformers](https://github.com/UKPLab/sentence-transformers) 6.1 + PyTorch 2.14 + numpy (`requirements/semantic.txt`) | ✅ Apache-2.0 / BSD | ✅ | No | `SEMANTIC_EMBEDDER=sentence_transformers`. Needs ~1 GB RAM and ~1–2 GB disk (CPU-only PyTorch is smaller); a VPS or your own machine, **not shared hosting** |
| Model | [`paraphrase-multilingual-MiniLM-L12-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) (default `SEMANTIC_MODEL`) | ✅ Apache-2.0 | ✅ after one download (~470 MB, Hugging Face cache) | No | 384 dimensions, 50+ languages incl. Hindi. Set `SEMANTIC_MODEL_LOCAL_ONLY=true` after the first download so the server never downloads at runtime. Loads in 10–20 s at server start (warm-up thread; keyword search meanwhile) |
| Vector search | In-repo cosine over one cached matrix (numpy when installed, plain Python otherwise) | ✅ project code | ✅ | No | Fine to roughly 10–20k products. FAISS / pgvector **not used**: unnecessary at this size and pgvector would tie search to PostgreSQL |

Setup with the model (development machine):
```powershell
cd backend
.\.venv\Scripts\pip install -r requirements\semantic.txt
# backend/.env:  SEMANTIC_EMBEDDER=sentence_transformers
.\.venv\Scripts\python manage.py rebuild_search_index      # first run downloads the model, then embeds every product
.\.venv\Scripts\python manage.py benchmark_search          # keyword vs hybrid on labelled queries (demo catalogue)
```
Switching embedders is safe at any time: vectors of the old one are ignored until `rebuild_search_index` replaces them,
and search works meanwhile (keyword + related words). `SEMANTIC_EMBEDDER=none` switches the embedding part off entirely.

## Photo search (Phase 14)
| Feature | Tool/Library | Free/Open Source | Local | API Key | Notes |
|---|---|---|---|---|---|
| Photo checks and cleaning | Pillow (already a dependency) | ✅ HPND | ✅ | No | Verify, EXIF removal, rotation, scaling. No new package |
| Default provider | `none` | ✅ project code | ✅ | No | Photo search answers "unavailable" and offers the word search. Production default (shared hosting) |
| Local, recommended for development | [CLIP](https://github.com/openai/CLIP) via sentence-transformers: **`clip-ViT-L-14`** (default `VISION_MODEL` for `clip`) | ✅ MIT (model) / Apache-2.0 (library) | ✅ after one download (~1.7 GB, Hugging Face cache) | No | `VISION_PROVIDER=clip`. Same packages as semantic search (`requirements/semantic.txt`). ~2 GB RAM, ~1.5 s per photo on a laptop CPU. Gives real probabilities and can only answer with known item kinds. `clip-ViT-B-32` (~600 MB, ~0.2 s) is lighter but recognised 9–10 of 13 test photos vs 12 of 13 (it took a claw hammer for a shovel) |
| Local, optional | Ollama + **`qwen2.5vl:3b`** (~3.2 GB) or `llava`, `moondream` | ✅ MIT runtime; Qwen2.5-VL 3B under the Qwen licence | ✅ | No | `VISION_PROVIDER=ollama`, `VISION_MODEL=qwen2.5vl:3b`. Describes things CLIP has no kind for; needs a GPU in practice (about 2 minutes per photo on a laptop CPU; 5 of 6 test photos right) and its confidence is its own estimate (capped, labelled) |
| Hosted, optional | Any OpenAI-compatible vision endpoint, or Anthropic | depends on the service | ❌ | Yes | Never enabled automatically; keys only in the server's `.env` |

Setup (development machine, CLIP):
```powershell
cd backend
.\.venv\Scripts\pip install -r requirements\semantic.txt     # if not done for semantic search
# backend/.env:  VISION_PROVIDER=clip
.\.venv\Scripts\python manage.py runserver                     # first start downloads clip-ViT-L-14 once
# afterwards: VISION_MODEL_LOCAL_ONLY=true (never download at runtime)
```
Photos are never stored. Throttle: `THROTTLE_IMAGE_SEARCH` (default 10/min). Limits: `IMAGE_SEARCH_MAX_BYTES` (8 MB).

## Storefront (Phase 16): no new dependencies
Sitemap and JSON-LD are generated by our own code (no SEO service); recently viewed uses browser storage; no analytics
or recommendation service was added.

## Loyalty and cashback (Phase 17): no new dependencies
Ledger, rules, jobs and wallet are our own Django/React code on the existing database and cron; no loyalty or wallet
service is used.

## Deliberately NOT used
Redis, Celery, RabbitMQ, Elasticsearch/OpenSearch, pgvector-only features, paid vector databases, AWS/Azure/GCP services,
Sentry SaaS, and any paid AI API. They are replaced by DB-backed queues + cron, DB cache, portable SQL search, and in-Python vector math.
