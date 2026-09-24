# BoltRun

AI-powered hardware marketplace with fast (~60-minute) delivery: a Django REST API and a React SPA.

> Status: **Phase 5 complete** (catalogue, cart, checkout with addresses and coupons, cash on delivery and a development
> mock online payment, order confirmation, history, detail and cancellation). See [TASKS.md](TASKS.md) and
> [docs/ROADMAP.md](docs/ROADMAP.md).
>
> Try it locally: register on the site, add products, check out with **Cash on delivery** or **Mock online payment**
> (you choose success / failure / cancellation; no money moves). Demo coupons: `DEMO10`, `DEMOFLAT50`.

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
- API health: http://127.0.0.1:8000/api/health/
- API docs: http://127.0.0.1:8000/api/docs/ (Swagger) · `/api/redoc/` · `/api/schema/`
- Django admin: http://127.0.0.1:8000/django-admin/ (`python manage.py createsuperuser`)

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
