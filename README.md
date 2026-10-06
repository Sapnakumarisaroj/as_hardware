# BoltRun

AI-powered hardware marketplace with fast delivery from nearby stores: a Django REST API and a React SPA. Delivery
times are calculated per order (store, distance, preparation, riders, workload), never a fixed promise.

> Status: **Phase 20 complete** — the quantity calculator at `/quantity`: "I need materials for 500 sq ft plastering",
> "How much paint for a 12x15 room?", "100 feet of wire", "tiles for 300 sq ft" or "Mujhe 500 sq ft ke liye plastering
> ka saman chahiye" → only the missing questions (any unit: ft, m, cm, mm, inch, sq ft, sq m), labelled assumptions
> ("Assumed: wall height 10 ft"), an estimated quantity with its breakdown, real catalogue products and the cheapest
> mix of packs (e.g. 4 L + 1 L), bulk prices, offers, coupon, stock and delivery time, then Add all to cart or save it
> as a project. Voice and the assistant use the same calculator; the optional local AI model only helps read unusual
> wording. **Phase 19** — the project builder at `/projects`: describe a job, answer a few questions, get a kit of real
> products priced as one cart. **Phase 18** — voice shopping at `/voice` (also the microphone in the search bar): say "10 bags of
> 53 grade cement", "das bori cement aur paanch pipe" or "दस बोरी सीमेंट कार्ट में डालो" and see the price for that
> quantity from the bulk tiers ("Add 20 more to pay ₹389 each"); it is added to the cart only after you say "yes" or tap
> Add. "Make it 30", "open my cart", "show me drills" and questions work too, answers are read aloud in English or
> Hindi, and typing always works. Uses the browser's own speech recognition (Chrome, Edge, Safari); optional local
> Whisper for other browsers, see [docs/FREE_TOOLS.md](docs/FREE_TOOLS.md). **Phase 17** — loyalty and cashback: a credit ledger (balance always added up from entries),
> cashback rules (e.g. 2 % on orders from ₹50,000) that stay pending until the return window after delivery has
> passed, promotional credit and referral codes, credits paying up to 20 % of an order at checkout (oldest expiry
> first, 90 days, never cash), automatic reversal and restore on cancellations and returns, a wallet page at
> `/account/wallet` and loyalty controls in the dashboard. No balances are seeded. **Phase 16** — the full storefront: a home page built from live data (departments, curated
> lists, department rails, bulk buying, offers, AI entry points, recently viewed), PIN-aware delivery (the fast badge
> appears only where the delivery engine can deliver fast to your PIN), product pages with bulk prices per quantity,
> offers, COD rules, delivery fee and free-delivery progress, uses/steps/FAQ and accessories, brand pages, category
> landing pages and search that understands "53 grade cement" or "50 kg cement". **Phase 15** added the commerce
> core (bulk prices, options, collections, offer types, free-delivery and COD rules).
> **Phase 14** added **search by photo** at `/image-search`, also from the camera button in the
> search bar: take or upload a photo of a tool or part and get what it most likely is, how sure we are, and the real
> catalogue products that match, with Add to Cart. When it isn't sure it says so and shows possible matches; photos are
> never stored. Off by default; for development set `VISION_PROVIDER=clip`, see [docs/FREE_TOOLS.md](docs/FREE_TOOLS.md)).
> **Phase 13** added **semantic search**: describe what you need — "machine for drilling concrete",
> "Mujhe diwar me hole karne ka saman chahiye", "hamer" — and the normal search finds real products by meaning, related
> words, Hindi/Hinglish and typos, with a short reason when the match isn't obvious; keyword search stays as the fallback.
> Administrators manage the index under **Search** in the dashboard. The optional local AI model is described in
> [docs/FREE_TOOLS.md](docs/FREE_TOOLS.md)). **Phase 12** added the AI hardware assistant at `/ai-assistant`: ask in English, Hindi or Hinglish, get real catalog products; works without an AI model in basic mode, see [docs/FREE_TOOLS.md](docs/FREE_TOOLS.md)). Earlier: **Phase 10 complete** (catalogue, cart, checkout with addresses, automatic offers and coupons, cash on delivery,
> online payments via Razorpay (ready; needs your keys) or the development mock gateway, verified webhooks, gateway
> refunds, order history, cancellation, returns and "Buy again", delivery zones, store selection and calculated
> delivery estimates, **the delivery partner app with delivery code, proof of delivery and cash collection, and
> live delivery tracking for customers**). Cron: `manage.py run_jobs` every 5 minutes. See [TASKS.md](TASKS.md)
> and [docs/ROADMAP.md](docs/ROADMAP.md).
>
> Try it locally: run `seed_demo_data`, register on the site, add products, check out with **Cash on delivery** or
> **Mock online payment** (you choose success / failure / cancellation; no money moves). Demo offers apply automatically
> (e.g. 10% off Tools on ₹1,500+); demo coupons `DEMO10` and `DEMOFLAT50` are listed at checkout.
>
> Delivery demo (Pune): set the PIN code in the header. `411038` (Kothrud) and `411045` (Baner) get **fast delivery**
> from their nearest store, `411001` gets **standard delivery** (extended zone, ₹60 fee), `411014` is **outside the
> delivery area**. Zones, fees, preparation time and riders are configured in the Django admin (Stores, Delivery).
> Maps are free and offline by default (OpenStreetMap services are optional: [docs/FREE_TOOLS.md](docs/FREE_TOOLS.md)).
>
> Rider demo: `python manage.py seed_demo_data --with-rider` creates `demo-rider@example.com` and prints its random
> password once. Then:
> 1. Sign in as the rider (you land on `/rider`) and press **Go online**.
> 2. As a customer (another browser or a private window), place an order to PIN `411038`.
> 3. In the Django admin, move the order to *Processing*, then *Packed* (order actions); under **Orders → Order
>    shipments** open the shipment and choose the rider in "Assign or reassign to".
> 4. In the rider app: accept the job, pick up, start the delivery.
> 5. The customer's order page now shows the **delivery code**; the rider enters it (and confirms the cash for a
>    cash-on-delivery order) to complete the delivery. Cash handover is recorded under **Delivery → Delivery
>    assignments**.
>
> Real delivery partners are created in the Django admin: a user with role *Delivery partner*, plus a *Delivery
> partner* record (home store, verified).

| | |
|---|---|
| Backend | Python 3.11+, Django 5.2 LTS, DRF, SimpleJWT, drf-spectacular |
| Database | PostgreSQL (preferred) · MySQL/MariaDB · SQLite (local), chosen via `DATABASE_URL` |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS 4, React Router, TanStack Query, Axios |
| Production | the owner's existing web hosting (Passenger `passenger_wsgi.py` + static SPA). See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |

## Quick start (Windows)

```powershell
Copy-Item .env.example .env     # set DJANGO_SECRET_KEY

cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements\dev.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_demo_data     # optional: DEMO catalog/stores/stock/images (dev only; --no-images to skip pictures)
.\.venv\Scripts\python manage.py rebuild_search_index   # semantic search index (kept current automatically afterwards)
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver

cd ..\frontend                  # second terminal
npm install
npm run dev
```

- App: http://localhost:5173
- Rider app (delivery partners): http://localhost:5173/rider
- Search by photo: http://localhost:5173/image-search (needs `VISION_PROVIDER=clip` or `ollama` in `backend/.env`)
- Shop by voice: http://localhost:5173/voice (Chrome/Edge/Safari; allow the microphone)
- Project builder: http://localhost:5173/projects · Quantity calculator: http://localhost:5173/quantity
- Business dashboard (administrators, store managers): http://localhost:5173/admin
- API health: http://127.0.0.1:8000/api/health/
- API docs: http://127.0.0.1:8000/api/docs/ (Swagger) · `/api/redoc/` · `/api/schema/`
- Django admin (rarely needed since Phase 11): http://127.0.0.1:8000/django-admin/ (`python manage.py createsuperuser` creates the first administrator, who can then use the dashboard)

Optional: `docker compose up --build` runs PostgreSQL + API + frontend locally. It is not needed for production.

## Checks

```powershell
# backend/
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
# frontend/
npm run lint; npm run typecheck; npm test; npm run build
```

## Documentation
- [Architecture](docs/ARCHITECTURE.md)
- [Database](docs/DATABASE.md)
- [API](docs/API.md)
- [Roadmap](docs/ROADMAP.md)
- [Deployment](docs/DEPLOYMENT.md), including the hosting questions to answer
- [Free tools & dependencies](docs/FREE_TOOLS.md)

## Principles
- AI never invents prices, stock, availability, reviews, compatibility or analytics. Every product fact comes from the database.
- External services (payments, WhatsApp, SMS, maps, LLM) are provider interfaces with free/mock defaults. Paid services are opt-in only.
- Secrets live only in environment variables. `.env` is gitignored.
