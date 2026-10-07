# Testing

How the platform is tested and how to run every suite. Results of the final run are in TASKS.md (Phase 26).

## 1. Backend (pytest)
```
cd backend
.venv\Scripts\python.exe -m pytest -q                         # every test (SQLite temp file DB)
.venv\Scripts\python.exe -m pytest -q --cov=apps --cov=integrations --cov-report=term-missing
.venv\Scripts\python.exe -m ruff check . ; .venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe manage.py spectacular --validate --file schema.yml   # OpenAPI: 0 errors expected
```
`config.settings.test` uses fast password hashing, in-memory file storage, the locmem email backend, fake
payment/vision/speech/LLM providers and generous rate limits (dedicated tests switch the real limits on).
Concurrency tests run real threads against a temporary SQLite file.

Production settings (`check --deploy` must show no `security.*` warnings):
```
set DJANGO_SETTINGS_MODULE=config.settings.prod
set DJANGO_SECRET_KEY=<64 random characters>
set DJANGO_ALLOWED_HOSTS=api.example.com
set PAYMENT_PROVIDER=none
.venv\Scripts\python.exe manage.py check --deploy
```

## 2. Frontend (Vitest + Testing Library)
```
cd frontend
npx vitest run
npx tsc -b --noEmit
npx eslint .
npx vite build
```
Tests render the real route table with a mocked API (`src/test/mockApi.ts`); every page is tested through what
the user sees and the requests it sends.

## 3. End-to-end over HTTP (`backend/e2e/`)
130 checks through the real API on a running server: registration, login, refresh rotation and replay, logout;
the ten categories, filters, search (incl. Hinglish), product detail, bulk quote, compatibility; wishlist, cart,
out-of-stock, coupons (valid and invalid), smart cart, recommendations, kits; AI assistant, voice, Quantity AI,
project builder, budget, image search (valid and invalid file); checkout preview, COD limit, price changed during
checkout (409), idempotent order placement, online payment failed → retried → paid, paying twice, cancelled
payment, cancel + stock release, cancel twice; delivery check, store transitions, manager/store isolation, rider
assignment, accept/pickup/start, wrong OTP, proof photo (invalid and valid; private to the customer), delivery with
OTP and cash, COD handover; failed delivery and re-dispatch; return → approve → receive → manual refund; inbox and
read state, delivery log, WhatsApp opt-in and mock; failed WhatsApp → admin retry; paid order cancelled → refund;
admin dashboard, products, offers (manager 403), inventory (store-scoped, never negative, ledgered), stores,
riders, customers, returns, reports, business assistant, no self role change; anonymous 401s, customer 403s,
avatar upload (non-image refused), 13 MB request (413), no self-promotion, unsigned webhooks refused.

```
cd backend
copy db.sqlite3 %TEMP%\e2e-copy.sqlite3            # a COPY of a seeded database (seed_demo_data)
set DATABASE_URL=sqlite:///%TEMP%/e2e-copy.sqlite3
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py shell -c "exec(open('e2e/setup.py').read())"
set THROTTLE_AUTH=1000/min & set THROTTLE_AI=1000/min & set THROTTLE_IMAGE_SEARCH=1000/min
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8026
.venv\Scripts\python.exe e2e\check.py http://127.0.0.1:8026/api        (second terminal)
```
`e2e/setup.py` refuses to run unless the database file name contains "e2e". Use a fresh copy each run (the
customers are registered through the API). After deployment the same script can be pointed at a staging copy.

Earlier phases' live suites (session scratchpad scripts, re-run in Phase 26): notifications 31 checks, reports and
business assistant with a local Ollama model 43 checks, security under production settings 19 checks.

## 4. What is not covered automatically
- No browser automation (Playwright isn't installed and the browser extension can't reach a local server); the
  pages are covered by the Vitest suite and the flows by the HTTP end-to-end script. A manual browser pass is part
  of the Phase 27 go-live checklist (DEPLOYMENT.md).
- No MySQL/PostgreSQL run: no server here. The code avoids vendor-specific SQL and date functions, but the suite
  must be run once on the hosting database before go-live (DEPLOYMENT.md).
- Real Razorpay, WhatsApp Cloud API and SMTP were never called (no accounts); their clients are tested against
  recorded/faked responses.
- Real-world load, and phones with real cameras/GPS for the rider app.
