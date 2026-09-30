# BoltRun

AI-powered hardware marketplace with fast delivery from nearby stores: a Django REST API and a React SPA. Delivery
times are calculated per order (store, distance, preparation, riders, workload), never a fixed promise.

> Status: **Phase 10 complete** (catalogue, cart, checkout with addresses, automatic offers and coupons, cash on delivery,
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
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver

cd ..\frontend                  # second terminal
npm install
npm run dev
```

- App: http://localhost:5173
- Rider app (delivery partners): http://localhost:5173/rider
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
