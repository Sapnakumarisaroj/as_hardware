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

## Blocked on owner input
- [ ] Hosting details (DEPLOYMENT.md §0 checklist): needed for Phase 24 only
- [ ] Confirm brand name ("BoltRun" placeholder)
- [ ] Choose local DB for dev parity: SQLite (current), Docker PostgreSQL, or local MySQL matching the host

## Phase 2 — Database + backend (next)
- [ ] Domain apps + portable models: catalog, locations, inventory, shopping, promotions, orders, payments, delivery, reviews, notifications, support, ai, analytics
- [ ] `core.Job` queue model
- [ ] Admin registrations
- [ ] `seed_dev` management command (dev-only data, refuses in prod)
- [ ] Model/constraint tests

## Later phases
See docs/ROADMAP.md (Phases 3–24).

## Environment notes
- Repo is inside OneDrive: consider excluding `backend/.venv` and `frontend/node_modules` from sync.
- Node is portable (not on PATH). Prefix commands with `$env:PATH="$env:LOCALAPPDATA\tools\node-v24.21.0-win-x64;$env:PATH"` or install Node LTS system-wide.
