# Deployment Guide

Target: **the owner's existing paid web hosting + domain.** No other hosting provider or paid service is required.

---

## 0. Hosting environment: status and required information

### What was inspected (2026-09-21)
| Source | Result |
|---|---|
| Project repository | Empty before Phase 1: no deploy config, `.cpanel.yml`, `.htaccess`, `sftp.json` or CI files |
| `~/.ssh/config` | Only private LAN hosts (`192.168.10.x`, port 3265). These look like office machines, **not** public web hosting |
| VS Code extensions | Remote-SSH only; no SFTP/FTP/cPanel deploy extension configured |
| FileZilla / WinSCP profiles | None found |

**Conclusion: the hosting environment cannot be detected from this machine.** Nothing about it has been assumed.
The app is built to run on the most restrictive common case (shared cPanel-style hosting with Passenger + MySQL + cron,
no Docker/Redis/workers), and every hosting-specific value is an environment variable.

### Please collect this from your hosting control panel
| # | Question | Where to find it (cPanel names; Plesk/hPanel are similar) |
|---|---|---|
| 1 | Hosting company and plan name (shared / cloud / VPS) | Billing / account dashboard |
| 2 | Control panel type (cPanel, Plesk, Hostinger hPanel, DirectAdmin, other) | Login page |
| 3 | Is there a **"Setup Python App"** (or "Python Selector") tool? Which Python versions does it list? | Software section |
| 4 | Is **SSH / Terminal** access available? | Advanced → Terminal, or "SSH Access" |
| 5 | Databases offered: **PostgreSQL** and/or **MySQL/MariaDB**? Exact version? | "PostgreSQL Databases" / "MySQL Databases"; the version shows in phpMyAdmin/phpPgAdmin |
| 6 | Can you create **subdomains** (e.g. `api.yourdomain.com`)? | Domains → Subdomains |
| 7 | Is **SSL (AutoSSL / Let's Encrypt)** active for the domain and subdomains? | SSL/TLS Status |
| 8 | Is **Cron Jobs** available, and what is the minimum interval? | Advanced → Cron Jobs |
| 9 | Disk quota, inode limit, and max upload size | Sidebar statistics / MultiPHP INI or Python App settings |
| 10 | Plan limits: RAM, CPU, entry processes, number of processes | Resource Usage / plan page |
| 11 | Is **Node.js** available ("Setup Node.js App")? *(Nice to have only: the frontend is built locally)* | Software section |
| 12 | Is outbound HTTPS allowed from apps (needed for Razorpay/WhatsApp APIs)? | Hosting docs / support |
| 13 | Email: can you create a mailbox and use SMTP? | Email Accounts |
| 14 | Is **Git Version Control** available in the panel? | Files → Git Version Control |

Once answered, record them here, and I will fix the deployment path (Passenger vs. VPS/gunicorn, MySQL vs. PostgreSQL).

### Decision table, by what the host offers
| If the host… | Then |
|---|---|
| has Python App (Passenger) + PostgreSQL | `DATABASE_URL=postgres://…` (preferred) |
| has Python App + only MySQL/MariaDB | `DATABASE_URL=mysql://…` + `pip install -r requirements/mysql.txt` (PyMySQL, no compiler needed) |
| offers Python 3.10+ | Django 5.2 LTS (current) |
| offers only Python ≤ 3.9 | tell me; the backend must be pinned to Django 4.2 LTS (supported until April 2026, **already out of security support**), so upgrading Python on the host is strongly preferred |
| has MariaDB < 10.5 or MySQL < 8.0.11 | too old for Django 5.2; ask the host for a newer DB version |
| has **no Python support at all** (PHP-only hosting) | the frontend can still be hosted there, but the Django API cannot. Options will be presented for your approval; nothing is purchased automatically |
| is a VPS with root | gunicorn + nginx + systemd; optional Docker; PostgreSQL |
| has no cron | `BACKGROUND_JOBS_MODE=inline` (notifications are sent during the request) |
| has no SSH | upload via File Manager/FTP; run `migrate`/`collectstatic` via the Python App "Execute python script" box |

---

## 1. Local setup (Windows + VS Code)

Prerequisites: Python 3.11+, Node.js 20+ (a portable Node 24 is fine), Git. Docker Desktop is **optional**.

```powershell
# from repo root
Copy-Item .env.example .env        # then set DJANGO_SECRET_KEY (see §2)

# Backend
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements\dev.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver          # http://127.0.0.1:8000/api/health/

# Frontend (new terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

Useful URLs: API docs at `http://127.0.0.1:8000/api/docs/`, Django admin at `http://127.0.0.1:8000/django-admin/`.

Checks: `pytest`, `ruff check .` (backend); `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (frontend).

Optional, free local extras:
- **Ollama** for AI features: install from ollama.com, run `ollama pull llama3.1:8b` (plus `llava` for images), then set `LLM_PROVIDER=ollama` and `LLM_MODEL=llama3.1:8b`.
- **Docker stack** with PostgreSQL: `docker compose up --build` (local only).

## 2. Environment variables

All configuration comes from environment variables. See `.env.example` for the full annotated list.

| Variable | Local | Production |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` (default in manage.py) | `config.settings.prod` (default in passenger_wsgi.py) |
| `DJANGO_SECRET_KEY` | any random string | **new** random 50+ chars: `python -c "import secrets;print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `true` | `false` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | `api.yourdomain.com` |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | `https://yourdomain.com,https://www.yourdomain.com` |
| `CSRF_TRUSTED_ORIGINS` | – | `https://api.yourdomain.com` |
| `DATABASE_URL` | blank → SQLite | `mysql://…` or `postgres://…` from the hosting panel |
| `STATIC_ROOT` / `MEDIA_ROOT` | blank → `backend/staticfiles`, `backend/media` | absolute paths on the host (§6, §7) |
| `PAYMENT_PROVIDER` | `mock` | `razorpay` (prod **refuses** `mock` unless `ALLOW_MOCK_PAYMENTS_IN_PROD=true`) |
| `WHATSAPP_PROVIDER`, `SMS_PROVIDER` | `mock` | `mock` until you connect real accounts |
| `LLM_PROVIDER` | `none` or `ollama` | `none` unless you choose and approve a provider |
| `BACKGROUND_JOBS_MODE` | `inline` | `cron` if cron is available |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | `https://api.yourdomain.com/api` (**build-time**; set before `npm run build`) |

Where to put production values, in order of preference:
1. the **environment variables** section of the control panel's "Setup Python App"
2. a `.env` file inside the app root (`backend/.env`), which is **not** web-accessible because the app root is outside `public_html`
3. a `.env` file at the path given in `ENV_FILE`

Never commit `.env`. `VITE_*` values are public (compiled into the JS bundle), so never put secrets there.

## 3. Database setup

**PostgreSQL (preferred, if offered)**
1. Control panel → PostgreSQL Databases: create the database and user, and grant ALL privileges.
2. `DATABASE_URL=postgres://USER:PASSWORD@localhost:5432/DBNAME`

**MySQL / MariaDB**
1. Control panel → MySQL Databases: create the database (collation `utf8mb4_unicode_ci`) and user, and grant ALL PRIVILEGES.
2. `DATABASE_URL=mysql://USER:PASSWORD@localhost:3306/DBNAME`
3. Install the driver: `pip install -r requirements/mysql.txt`

Notes: cPanel prefixes names (`cpaneluser_boltrun`), so use the full prefixed names. URL-encode special characters in the password (`@` → `%40`, etc.).

Cache table for rate limiting (once, after migrate): `python manage.py createcachetable`

Backups: enable the host's automatic backups. Also schedule a dump via cron, e.g.
`mysqldump --single-transaction DB > ~/backups/boltrun-$(date +\%F).sql`, keeping the backups outside `public_html`.

## 4. Frontend build

Built **locally**; the server needs no Node.js.
```powershell
cd frontend
$env:VITE_API_BASE_URL="https://api.yourdomain.com/api"; $env:VITE_APP_NAME="BoltRun"
npm ci
npm run build          # -> frontend/dist/
```
Upload the **contents** of `dist/` (including the hidden `.htaccess`) to the main domain's document root
(usually `public_html/`). `.htaccess` provides the SPA route fallback (`/products/123` → `index.html`), security headers,
and long-lived caching for hashed assets.

## 5. Backend deployment (cPanel "Setup Python App" / Passenger)

Recommended layout: SPA on `yourdomain.com`, API on the `api.yourdomain.com` subdomain.

1. Domains → create subdomain `api.yourdomain.com`.
2. Setup Python App → **Create Application**:
   - Python version: highest available, **3.10+**
   - Application root: `boltrun_api` (outside `public_html`)
   - Application URL: `api.yourdomain.com`
   - Startup file: `passenger_wsgi.py`, entry point `application`
3. Upload the contents of `backend/` into `~/boltrun_api/` (via Git, File Manager zip upload, or SFTP), **excluding** `.venv/`,
   `db.sqlite3`, `media/` and `staticfiles/`.
4. Set the environment variables (§2) in the Python App screen, or create `~/boltrun_api/.env`.
5. Open a terminal (or use the "Enter to the virtual environment" command the panel shows):
   ```bash
   source ~/virtualenv/boltrun_api/3.11/bin/activate   # exact path shown in the panel
   cd ~/boltrun_api
   pip install -r requirements/prod.txt
   pip install -r requirements/mysql.txt                # only if using MySQL
   python manage.py migrate --noinput
   python manage.py createcachetable
   python manage.py collectstatic --noinput
   python manage.py check --deploy
   python manage.py createsuperuser
   ```
6. **Restart** the app from the panel (or `touch tmp/restart.txt`).
7. Verify: `https://api.yourdomain.com/api/health/` → `{"status":"ok", … "database":"ok"}`.

Without SSH, run the same commands through the panel's "Run script" / "Execute python script" feature, or ask the host's support.

Background jobs (if cron exists), every minute:
```
* * * * * cd ~/boltrun_api && ~/virtualenv/boltrun_api/3.11/bin/python manage.py run_jobs --max-seconds 50 >> ~/logs/boltrun_jobs.log 2>&1
```
(`run_jobs` ships with the job queue in Phase 8/20.)

**Alternative, single domain** (if subdomains aren't possible): mount the Python app at `yourdomain.com/api`. That needs a
small URL-prefix change; ask before choosing this.

**VPS alternative:** `gunicorn config.wsgi:application` behind nginx, with systemd units. `backend/Dockerfile` (`prod`
target) is available if Docker is present.

## 6. Static files

Django admin and DRF assets are collected into `STATIC_ROOT` and served by **WhiteNoise** from inside the Python app, so
no extra web-server configuration is needed. The default `STATIC_ROOT` (`~/boltrun_api/staticfiles`) is fine.
Re-run `collectstatic` after every deploy. The SPA's own assets are the static `dist/` files from §4.

## 7. Media files (product images, delivery proof)

Stored on the host's disk. Two options:
- **Simple (recommended):** `MEDIA_ROOT=/home/USER/api.yourdomain.com/media` (the subdomain's document root) and
  `MEDIA_URL=https://api.yourdomain.com/media/`. Apache serves the files directly.
- **Private files** (e.g. delivery proof photos) are stored outside the document root and served through an authenticated API endpoint.

Uploads are validated (type, size, Pillow verification) and renamed randomly. Watch the disk and inode quota (§0 #9).
Add `Options -Indexes` in the media folder's `.htaccess`, and block script execution there:
```
Options -Indexes
<FilesMatch "\.(php|py|pl|cgi|sh)$">
  Require all denied
</FilesMatch>
```

## 8. Migrations

- Always back up the DB before migrating (§3).
- Run `python manage.py migrate --noinput` after uploading new code and before restarting the app.
- Check first with `python manage.py showmigrations` / `python manage.py migrate --plan`.
- Migrations are written to be vendor-portable. PostgreSQL-only optimisations no-op on MySQL.
- Never edit an applied migration. Create a new one instead.

## 9. Domain configuration

- `yourdomain.com` and `www` → the hosting account (usually already set when domain and hosting are with the same provider;
  otherwise point the domain's nameservers or an A record to the host's IP shown in the panel).
- Create the subdomain `api.yourdomain.com` in the panel. If DNS is managed elsewhere, add an A/CNAME record to the same host.
- Update `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and rebuild the frontend with the right
  `VITE_API_BASE_URL`.
- Webhook URLs to register later: `https://api.yourdomain.com/api/payments/webhooks/razorpay/`,
  `https://api.yourdomain.com/api/support/webhooks/whatsapp/`.

## 10. HTTPS / SSL

- Enable **AutoSSL / Let's Encrypt** in the panel for `yourdomain.com`, `www.yourdomain.com` and `api.yourdomain.com`
  (free with most plans).
- After the certificate is active, uncomment the HTTPS redirect lines in `public_html/.htaccess`.
- Django prod settings already set: `SECURE_SSL_REDIRECT`, HSTS (1 year), secure cookies, and `SECURE_PROXY_SSL_HEADER`.
  If the site redirect-loops behind the host's proxy, set `SECURE_SSL_REDIRECT=false` and let `.htaccess` handle the redirect.
- Razorpay and WhatsApp webhooks require HTTPS.

## 11. Production settings checklist

- [ ] `DJANGO_SETTINGS_MODULE=config.settings.prod`, `DJANGO_DEBUG=false`
- [ ] new `DJANGO_SECRET_KEY` (never reuse the dev key)
- [ ] `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` set to real domains
- [ ] `DATABASE_URL` points to the hosting DB; `createcachetable` run
- [ ] `PAYMENT_PROVIDER=razorpay` with live keys (or COD-only launch with mock blocked)
- [ ] SMTP credentials for password reset and order emails
- [ ] `python manage.py check --deploy` shows no issues
- [ ] Frontend built with the production `VITE_API_BASE_URL`
- [ ] SSL active on all three hostnames
- [ ] DB backups scheduled
- [ ] Cron job for `run_jobs` (if `BACKGROUND_JOBS_MODE=cron`)

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "Incomplete response received from application" / 500 on every request | Check the Passenger log (`~/boltrun_api/stderr.log` or the panel's log). Usually a missing env var (`DJANGO_SECRET_KEY`) or `pip install` not run inside the app's virtualenv |
| `ImproperlyConfigured: PAYMENT_PROVIDER=mock in production` | Intended safety guard. Set `PAYMENT_PROVIDER=razorpay`, or `ALLOW_MOCK_PAYMENTS_IN_PROD=true` on staging only |
| `Error loading MySQLdb module` | `pip install -r requirements/mysql.txt` in the app's virtualenv |
| `Access denied for user` | Use the full cPanel-prefixed DB name and user; grant privileges; URL-encode the password |
| `DisallowedHost` | Add the hostname to `DJANGO_ALLOWED_HOSTS` |
| Browser CORS error | Add the exact frontend origin (scheme + host, no trailing slash) to `CORS_ALLOWED_ORIGINS` |
| SPA routes 404 on refresh | `.htaccess` wasn't uploaded (hidden file) or `mod_rewrite` is disabled |
| Admin has no CSS | Run `collectstatic`, then restart the app |
| Code changes not visible | Restart the app (`touch tmp/restart.txt`) |
| Redirect loop after enabling SSL | `SECURE_SSL_REDIRECT=false` (let Apache redirect) |
| `health` returns `"database":"unavailable"` (503) | DB credentials or host wrong, or the DB is down. Check the log for the request ID shown in the `X-Request-ID` header |
| Processes killed / slow | Plan resource limits (§0 #10). Lower Passenger workers; keep `LLM_PROVIDER=none` on shared hosting |
