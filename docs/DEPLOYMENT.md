# Deployment Guide

Target: **the Hostinger VPS (Ubuntu, Docker) for `ashardwareandplywood.com`** — section A. Sections 0–12 below describe
the shared-hosting (cPanel/Passenger) alternative and are kept for reference.

The Ajoriya Interiors website runs on separate Hostinger shared hosting: nothing here touches its hosting or DNS.

---

## A. Hostinger VPS with Docker (production)

### A1. What runs

```
Internet ─► caddy :80/:443 (HTTPS, Let's Encrypt) ─► web :8080 (nginx: React site, /api proxy, /media)
                                                       └─► backend :8000 (Django + gunicorn) ─► db :5432 (PostgreSQL 16)
                                                           jobs (run_jobs every minute: refunds, order expiry, notifications)
```

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | The five services, private networks, volumes, restart policies, health checks |
| `backend/Dockerfile` (`prod`) | Python 3.11 + gunicorn; static files collected at build time (WhiteNoise) |
| `frontend/Dockerfile` (`prod`) | Builds the site (`VITE_API_BASE_URL=/api`) and serves it with nginx |
| `frontend/nginx/*.conf` | SPA routing, `/api/` `/django-admin/` `/static/` `/sitemap.xml` → Django, `/media/`, cache + security headers, 12 MB uploads |
| `deploy/Caddyfile` | HTTPS for `SITE_DOMAIN` (and `www.` → redirect). No other domain is served |
| `.env.production.example` | Template for the server's `.env` (placeholders only) |
| `deploy/backup.sh` | PostgreSQL dump + public and private media archives |
| `catalogue/build_release.py` | Builds and verifies the catalogue import package (`catalogue/release/`, private) |

Same domain for site and API: no CORS, one certificate, cookies and CSRF on one origin.

Safety built in:
- PostgreSQL has **no published port** and sits on an `internal` network (no route in or out). Django is not published
  either; the only public ports are Caddy's 80/443. (Docker-published ports bypass UFW, so nothing else is published;
  `web` listens on `127.0.0.1:8080` only, for checks on the server.)
- Production settings refuse: `DEBUG` (never read), a weak `DJANGO_SECRET_KEY`, an empty or `*` `DJANGO_ALLOWED_HOSTS`,
  **SQLite or a missing `DATABASE_URL`**, `PAYMENT_PROVIDER=mock`, and `razorpay` without all three keys.
- COD only at launch: `PAYMENT_PROVIDER=none` (online payment shown as unavailable). SMS/OTP sign-in stays off
  (`OTP_LOGIN_ENABLED=False`; the site is built with `VITE_OTP_LOGIN_ENABLED=false`); customers use mobile number + password.
- Secrets live only in the server's `.env` (git-ignored, `chmod 600`) and are never baked into images (`.dockerignore`).
- Private media (delivery proof photos) is in its own volume that nginx cannot read.

### A2. One-time server preparation

1. SSH in as a sudo user (not root). Update: `sudo apt update && sudo apt upgrade -y`.
2. Firewall: `sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp && sudo ufw enable`.
3. Swap (helps builds on 8 GB): `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
   and add `/swapfile none swap sw 0 0` to `/etc/fstab`.
4. Docker is installed (29.x, Compose v5). Add your user to the `docker` group or use `sudo`.
5. Code: `git clone https://github.com/Sapnakumarisaroj/as_hardware.git /opt/ashardware && cd /opt/ashardware`
   (then `git checkout <release commit>`).

### A3. Configuration (`.env`, never committed)

```bash
cd /opt/ashardware
cp .env.production.example .env && chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # → DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"       # → POSTGRES_PASSWORD (letters/digits: it goes in a URL)
nano .env                                                        # replace every CHANGE_ME
grep -n CHANGE_ME .env                                           # must print nothing
```
Required: `SITE_DOMAIN`, `ACME_EMAIL`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` (the domain first),
`CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL`, `POSTGRES_*`, SMTP (`EMAIL_*`, `DEFAULT_FROM_EMAIL`: password reset and order
emails), `INVOICE_SELLER_*`. Keep `PAYMENT_PROVIDER=none`, `OTP_LOGIN_ENABLED=False`, `TRUSTED_PROXY_COUNT=2`.
Never paste `.env` into chats, tickets or Git.

### A4. Build and start (before DNS points here)

```bash
sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$(git rev-parse --short HEAD)/" .env   # images tagged per release, kept in .env (rollback, A8)
C="docker compose -f docker-compose.prod.yml"
$C build
$C run --rm backend python manage.py check --deploy  # must report no security issues
$C up -d db
```

### A5. First deployment: database, catalogue, admin

The catalogue package is **private** (it holds the reviewed prices): build it on the owner's PC and copy it over SSH,
never through Git.

On the PC (`C:\dev\as_hardware`):
```powershell
.\.venv\Scripts\python -I catalogue\build_release.py          # validates everything; writes catalogue\release\
scp -r catalogue\release user@VPS:/opt/ashardware/catalogue/   # 01_products.csv, 02_images.csv, 03_publish.csv,
                                                               # shop_setup.json, REPORT.md, SHA256SUMS
```

On the VPS:
```bash
cd /opt/ashardware && C="docker compose -f docker-compose.prod.yml"
(cd catalogue/release && sha256sum -c SHA256SUMS)              # the copy is complete and unchanged
M="-v $PWD/catalogue:/srv/catalogue:ro -v $PWD/assets:/srv/assets:ro"
$C run --rm backend python manage.py migrate --noinput
$C run --rm backend python manage.py createcachetable          # rate-limit cache (database cache)
$C run --rm backend python manage.py apply_taxonomy --dry-run
$C run --rm backend python manage.py apply_taxonomy
$C run --rm $M backend python manage.py loaddata /srv/catalogue/release/shop_setup.json   # store BLR-01, delivery zone, charges
$C run --rm $M backend python manage.py import_catalog /srv/catalogue/release/01_products.csv            # dry run
$C run --rm $M backend python manage.py import_catalog /srv/catalogue/release/01_products.csv --commit   # products, prices, GST, stock
$C run --rm $M backend python manage.py import_product_images /srv/catalogue/release/02_images.csv --root /srv/assets/as-hardware-images --commit
$C run --rm $M backend python manage.py import_catalog /srv/catalogue/release/03_publish.csv --commit    # publish (after pictures)
$C run --rm backend python manage.py rebuild_search_index
$C run --rm backend python manage.py createsuperuser           # the owner's admin account (prompts for the password)
```
Run `loaddata shop_setup.json` only on a **new, empty** database (it writes fixed ids: store 1, zone 1, charges 1; the
zone links to the Bengaluru service area that `migrate` creates as id 1).

Check that the database matches the package (prices, approval, stock, GST/HSN, published state):
```bash
install -d -m 777 /tmp/ashw     # the container runs as an unprivileged user
$C run --rm -v /tmp/ashw:/out backend python manage.py export_catalog --output /out/export.csv
python3 -I catalogue/build_release.py --verify /tmp/ashw/export.csv     # must print "0 difference(s)"
rm -rf /tmp/ashw
```
Never run `seed_demo_data` on this server.

### A6. Start everything and check (still before DNS)

```bash
$C up -d
$C ps                                        # db, backend, web: healthy; jobs, caddy: running
$C logs --tail=50 backend jobs
curl -s -H "Host: ashardwareandplywood.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8080/api/health/
#   → {"status":"ok", … "database":"ok"}
curl -sI -H "Host: ashardwareandplywood.com" http://127.0.0.1:8080/products/x | head -1   # 200 (SPA route)
```
From your PC (SSH tunnel), browse the site before DNS: `ssh -L 8080:127.0.0.1:8080 user@VPS`, then open
`http://localhost:8080` to look at pages. The API refuses that address (production host and HTTPS checks), so test
sign-in and checkout after DNS + HTTPS (A7).

### A7. DNS and HTTPS (owner's step, when ready)

Only for `ashardwareandplywood.com` (never the Ajoriya Interiors domain): an `A` record for `@` and for `www` to the
VPS IP. Caddy then obtains the certificates by itself (watch `$C logs -f caddy`). Check:
- `https://ashardwareandplywood.com/api/health/` → `"database":"ok"`; `http://` redirects to `https://`; `www.` redirects.
- Sign up with a mobile number + password, add to cart, checkout with **cash on delivery**, see the order in `/admin`.
- Set the store's map location (Dashboard › Stores › BLR-01) once verified: distance-based delivery charges need it.

### A8. Updates and rollback

```bash
cd /opt/ashardware && C="docker compose -f docker-compose.prod.yml"
bash deploy/backup.sh                          # ALWAYS before an update
git fetch && git checkout <new commit>
sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$(git rev-parse --short HEAD)/" .env
$C build
$C run --rm backend python manage.py migrate --plan     # read what will change
$C run --rm backend python manage.py migrate --noinput
$C up -d
```
Rollback (code only, no migration since the previous release): `git checkout <previous commit>`,
set `RELEASE_TAG=<previous short hash>` in `.env` (its images are still on the server), `$C up -d`.
The tag lives in `.env` (not a shell `export`) so every later `$C up -d`, in any session, uses the same images.
Rollback after a migration: restore the database from the backup taken just before (A9), then roll back the code.
Never edit an applied migration. `docker image prune` only after a release has proved itself.

### A9. Backups and restore

Nightly (as root, `crontab -e`):
```
30 2 * * * cd /opt/ashardware && bash deploy/backup.sh >> /var/log/ashardware-backup.log 2>&1
```
Writes `/var/backups/ashardware/db-<time>.dump`, `media-<time>.tar.gz`, `private_media-<time>.tar.gz` (mode 600), keeps
14 days. Also copy them off the server regularly (e.g. `scp` to the owner's PC or Hostinger's backup storage).

Restore (stop writers first: `$C stop web jobs backend`):
```bash
# Database (replaces the current data):
$C exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
  < /var/backups/ashardware/db-<time>.dump
# Public media / private media:
docker run --rm -v ashardware_media:/data -v /var/backups/ashardware:/backup alpine:3 \
  sh -c 'rm -rf /data/* && tar -xzf /backup/media-<time>.tar.gz -C /data'
docker run --rm -v ashardware_private_media:/data -v /var/backups/ashardware:/backup alpine:3 \
  sh -c 'rm -rf /data/* && tar -xzf /backup/private_media-<time>.tar.gz -C /data'
$C up -d
```
Test a restore once on a scratch copy before launch (e.g. restore into a second project with `-p ashw-restore-test`).

### A10. Later, each with the owner's approval

- Live payments: Razorpay live keys + webhook (§5 "Razorpay go-live"), `PAYMENT_PROVIDER=razorpay`.
- SMS/OTP sign-in: a real SMS gateway (MSG91 + DLT), then `OTP_LOGIN_ENABLED=True` and a rebuild of `web` with
  `VITE_OTP_LOGIN_ENABLED=true`.
- WhatsApp Cloud API (§5 "WhatsApp go-live").

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
| `PRIVATE_MEDIA_ROOT` | blank → `backend/private_media` | a folder outside the document roots (§7) |
| `DELIVERY_OTP_*`, `DELIVERY_PROOF_REQUIRED`, `DELIVERY_EARNING_*` | defaults | optional; see `.env.example` (Phase 10) |
| `PAYMENT_PROVIDER` | `mock` | `razorpay`, or `none` for a cash-on-delivery-only launch (online payment shown as unavailable). Prod **refuses** `mock` unless `ALLOW_MOCK_PAYMENTS_IN_PROD=true`, which is for staging only: with it anyone could confirm an online order without paying |
| `WHATSAPP_PROVIDER`, `SMS_PROVIDER` | `mock` | `mock` until you connect real accounts (messages are recorded in the delivery log, nothing is sent; customers still get in-app + email). WhatsApp: `meta` with `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` (see “WhatsApp go-live”). SMS: no gateway ships (paid); keep `mock` or `none` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | console | the hosting mailbox's SMTP details: order, delivery, refund and support emails go out through it |
| `LLM_PROVIDER` | `none` or `ollama` | `none` unless you choose and approve a provider |
| `BACKGROUND_JOBS_MODE` | `inline` | `cron` if cron is available (also makes password-reset responses take the same time for every email) |
| `DJANGO_ENV` | `development` | `production` (development settings then refuse to load) |
| `TRUSTED_PROXY_COUNT` | `0` | proxies in front of Django that append to X-Forwarded-For (0 when Apache/Passenger passes the client address as REMOTE_ADDR; 1 behind one reverse proxy or CDN). Wrong values let clients fake their address for rate limits |
| `MAX_REQUEST_BYTES` | `12582912` | largest request accepted (12 MB); also set Apache `LimitRequestBody 12582912` |
| `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD` | – | `31536000`, `true`, `true` once every subdomain serves HTTPS (lower/false while testing) |
| `SEMANTIC_EMBEDDER` | `hashing` | `hashing` on shared hosting; `sentence_transformers` only on a VPS with ~1 GB spare RAM (`requirements/semantic.txt`, `SEMANTIC_MODEL_LOCAL_ONLY=true`). After deploying run `manage.py migrate`, `manage.py apply_taxonomy` (the approved categories; `--dry-run` first) then `manage.py rebuild_search_index` once |
| `SPEECH_STT_PROVIDER` / `SPEECH_TTS_PROVIDER` | `none` | `none` on shared hosting: voice shopping (`/voice`) then uses the browser's own speech recognition and voice. `faster_whisper` only on a VPS with ~1 GB spare RAM (`requirements/speech.txt`, `SPEECH_MODEL_LOCAL_ONLY=true` after the first download), for browsers that can't listen. The upload limit must allow `VOICE_MAX_AUDIO_BYTES` (2 MB) |
| `VISION_PROVIDER` | `none` | `none` on shared hosting (photo search then offers the word search); `clip` only on a VPS with ~2 GB spare RAM (`requirements/semantic.txt`, `VISION_MODEL_LOCAL_ONLY=true` after the first download). The web server's upload limit must allow `IMAGE_SEARCH_MAX_BYTES` (8 MB) |
| `VITE_API_BASE_URL` | `http://localhost:8000/api` | `https://api.yourdomain.com/api` (**build-time**; set before `npm run build`) |
| `ROUTING_PROVIDER` | `haversine` (offline) | `haversine`, or `osrm` with `OSRM_BASE_URL` (§2a) |
| `GEOCODING_PROVIDER` | `none` (offline) | `none`, or `nominatim` with `NOMINATIM_USER_AGENT` (§2a) |
| `VITE_MAP_TILE_URL`, `VITE_MAP_CENTER` | blank → OpenStreetMap tiles, map opens on Pune | your city's `lat,lng` (**build-time**) |

Where to put production values, in order of preference:
1. the **environment variables** section of the control panel's "Setup Python App"
2. a `.env` file inside the app root (`backend/.env`), which is **not** web-accessible because the app root is outside `public_html`
3. a `.env` file at the path given in `ENV_FILE`

Never commit `.env`. `VITE_*` values are public (compiled into the JS bundle), so never put secrets there.

### 2a. Delivery engine setup (Phase 9)

Delivery works out of the box with **no external service** (`ROUTING_PROVIDER=haversine`, `GEOCODING_PROVIDER=none`).
What it needs is real data, entered once in the business dashboard (`/admin` → Stores, as an administrator; the
Django admin at `/django-admin/` works too):

1. **Stores** → each store: address, PIN code, **latitude/longitude** (right-click the spot on openstreetmap.org →
   "Show address" shows the coordinates), opening hours, preparation time, and "Own riders" if riders don't use the
   partner app. A store without coordinates can only serve PIN codes listed in its zones.
2. **Delivery zones** (on the store page or under Delivery → Delivery zones): radius and/or PIN codes, fee and
   free-delivery threshold (blank = the global `DELIVERY_FEE` / `FREE_DELIVERY_MIN_ORDER`), fast delivery on/off and
   its cutoff. **A store without an active zone receives no orders.**
3. **PIN codes** (Delivery → PIN codes): the approximate centre of each PIN code you serve, so customers who have
   only typed a PIN (or saved an address without a map pin) get a distance-based estimate.
4. **Delivery partners**: verified, with a home store and "Deliveries at once". Fast delivery is offered only while
   a rider (app partner or own rider) can take the order.

Tuning (environment variables; all optional, defaults in `.env.example`): `FAST_DELIVERY_MAX_MINUTES`,
`DELIVERY_AVG_SPEED_KMPH`, `ROAD_DISTANCE_FACTOR`, `DELIVERY_HANDOVER_MINUTES`, `DELIVERY_RIDER_TURNAROUND_MINUTES`,
`STANDARD_DISPATCH_DELAY_MINUTES`, `STANDARD_WINDOW_MINUTES`, `SPLIT_FULFILLMENT_ENABLED`, `MAX_SHIPMENTS_PER_ORDER`.
`TIME_ZONE` is `Asia/Kolkata`; opening hours are in that time zone.

**Optional OpenStreetMap services** (free, but with usage limits: see FREE_TOOLS.md):
- `ROUTING_PROVIDER=osrm`: road distances from OSRM. The public demo server (`OSRM_BASE_URL` default) is for light
  use only; for production traffic point `OSRM_BASE_URL` at your own OSRM (needs a VPS; not possible on shared hosting).
- `GEOCODING_PROVIDER=nominatim`: set `NOMINATIM_USER_AGENT="YourSite/1.0 (you@yourdomain.com)"`.
- Both need **outbound HTTPS** from the hosting account (some shared hosts block it; ask support, or stay offline).
  If a service is unreachable the engine silently uses the offline estimate.
- OSRM results are cached in Django's cache, so run `createcachetable` (§3).

**Frontend map.** The address form loads map tiles from `tile.openstreetmap.org` in the customer's browser. If you
add a Content-Security-Policy header, allow that host in `img-src`. "Use my current location" works only on HTTPS.

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
$env:VITE_API_BASE_URL="https://api.yourdomain.com/api"; $env:VITE_APP_NAME="AS Hardware and Plywood"
npm ci
npm run build          # -> frontend/dist/
```
Upload the **contents** of `dist/` (including the hidden `.htaccess`) to the main domain's document root
(usually `public_html/`). `.htaccess` provides the SPA route fallback (`/products/123` → `index.html`), security headers,
and long-lived caching for hashed assets.

The business dashboard (Phase 11) is part of this build at `https://yourdomain.com/admin` and needs nothing extra on
the server: the same SPA fallback serves it, and it talks to the API like the shop does. Sign in with an `admin` or
`store_manager` account (create the first administrator with `python manage.py createsuperuser`, or give an existing
account the role in the dashboard under Customers). Django's own admin stays at `https://api.yourdomain.com/django-admin/`
for rare tasks and is protected by the same accounts.

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

Background jobs (Phase 8), every 5 minutes. Set `BACKGROUND_JOBS_MODE=cron`. This submits refunds, recovers
payments whose confirmation never arrived, and cancels unpaid online orders after `PAYMENT_EXPIRY_MINUTES`:
```
*/5 * * * * cd ~/boltrun_api && ~/virtualenv/boltrun_api/3.11/bin/python manage.py run_jobs --max-seconds 240 >> ~/logs/boltrun_jobs.log 2>&1
```
`python manage.py payments_check` lists any payment/order/refund records that disagree (exit code 1), which is useful
after a deploy. Without cron, payments still work (checkout verification + webhooks), but refunds are only submitted
inline and unpaid orders don't expire.

Notifications (Phase 23) are sent by the same `run_jobs` cron in `cron` mode (immediately after the request in
`inline` mode); the cron also sends one "running late" message for orders past their estimate
(`DELIVERY_DELAY_NOTICE_MINUTES`). Failed messages are listed in the dashboard (Notifications → Delivery log) with a
"Send again" button.

WhatsApp go-live (only after the owner decides to pay for it): create a WhatsApp Business account and app in Meta's
developer console, add the shop's phone number, and get these templates approved in WhatsApp Manager with the variables
shown in the dashboard (Notifications → Messages → WhatsApp words), in the same order: `order_confirmed`,
`payment_received`, `out_for_delivery`, `delivery_code`, `delivery_delayed`, `order_delivered`, `delivery_failed`,
`delivery_retry`, `order_cancelled`, `reorder_ready`, `refund_started`, `refund_completed`, `return_update`,
`support_reply` (only those for events switched on for WhatsApp are needed). Put `WHATSAPP_PROVIDER=meta`,
`WHATSAPP_ACCESS_TOKEN` (a permanent system-user token), `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` (the app's
secret) and a random `WHATSAPP_VERIFY_TOKEN` in `.env`, restart, then register the webhook
`https://api.yourdomain.com/api/notifications/webhooks/whatsapp/` with that verify token and subscribe to `messages`.
The Notifications → Channels screen then shows WhatsApp as "Live". Customers receive WhatsApp only after opting in.

Razorpay go-live: put the live keys in `.env` (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`), then create a webhook in the
Razorpay dashboard for `https://api.yourdomain.com/api/payments/webhooks/razorpay/` with a secret
(`RAZORPAY_WEBHOOK_SECRET`) and the events `payment.captured`, `payment.failed`, `order.paid`, `refund.processed` and
`refund.failed`. Enable auto-capture in the dashboard; authorised-only payments are captured by the server anyway.

**Alternative, single domain** (if subdomains aren't possible): mount the Python app at `yourdomain.com/api`. That needs a
small URL-prefix change; ask before choosing this.

**VPS:** see section A (Docker: Caddy + nginx + gunicorn + PostgreSQL), the chosen production setup.

## 6. Static files

Django admin and DRF assets are collected into `STATIC_ROOT` and served by **WhiteNoise** from inside the Python app, so
no extra web-server configuration is needed. The default `STATIC_ROOT` (`~/boltrun_api/staticfiles`) is fine.
Re-run `collectstatic` after every deploy. The SPA's own assets are the static `dist/` files from §4.

## 7. Media files (product images, delivery proof)

Stored on the host's disk. Two options:
- **Simple (recommended):** `MEDIA_ROOT=/home/USER/api.yourdomain.com/media` (the subdomain's document root) and
  `MEDIA_URL=https://api.yourdomain.com/media/`. Apache serves the files directly.
- **Private files** (proof-of-delivery photos, Phase 10) are stored in `PRIVATE_MEDIA_ROOT` and served only through
  authenticated API endpoints. Set it to a folder **outside every document root**, e.g.
  `PRIVATE_MEDIA_ROOT=/home/USER/boltrun_private`, writable by the app. The default (`private_media/` inside the
  app root) is safe as long as the app root is not web-served, which is the case in §5. Never put it under
  `public_html` or under `MEDIA_ROOT`. Check after deploying: uploading a delivery photo works, and
  `https://api.yourdomain.com/media/delivery-proofs/` answers 404. Include the folder in your backups.

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
  `https://api.yourdomain.com/api/notifications/webhooks/whatsapp/`.

### Sitemap and robots (Phase 16)
- The API serves the sitemap at `https://api.yourdomain.com/api/seo/sitemap.xml` with absolute URLs on `FRONTEND_URL`
  (set `FRONTEND_URL=https://yourdomain.com`). Make it available as `https://yourdomain.com/sitemap.xml` with a
  rewrite in `public_html/.htaccess` (`RewriteRule ^sitemap\.xml$ https://api.yourdomain.com/api/seo/sitemap.xml [P,L]`
  where proxying is allowed, otherwise `[R=302,L]`), and add `Sitemap: https://yourdomain.com/sitemap.xml` to
  `public_html/robots.txt`. Submit it in Google Search Console (free).

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
- [ ] `PAYMENT_PROVIDER=razorpay` with live keys, or `PAYMENT_PROVIDER=none` for a COD-only launch (never `mock`)
- [ ] SMTP credentials for password reset and order emails
- [ ] `python manage.py check --deploy` shows no issues
- [ ] Frontend built with the production `VITE_API_BASE_URL`
- [ ] SSL active on all three hostnames
- [ ] DB backups scheduled
- [ ] Cron job for `run_jobs` (if `BACKGROUND_JOBS_MODE=cron`)
- [ ] `PRIVATE_MEDIA_ROOT` is outside the document roots and writable; proof photos are not reachable by URL (§7)
- [ ] Delivery partners: user with role `delivery_partner` + a Delivery partner record (home store, verified) in the Django admin; they sign in at `/login` and work at `/rider`. The site must run on HTTPS for the phone camera and location to work
- [ ] Stores have coordinates, opening hours and at least one active delivery zone; PIN codes entered (§2a)
- [ ] `GET /api/delivery/check/?postal_code=<a PIN you serve>` answers `serviceable: true`, and a PIN you don't serve `false`

### Go-live test pass (Phase 26 → 27)
Everything below was tested in development (docs/TESTING.md); these checks need the real host:
- [ ] Run the backend suite once against the hosting database engine (MySQL or PostgreSQL):
  `DATABASE_URL=<a scratch database on that server> python -m pytest -q`
- [ ] Copy the production database to a scratch database, run `e2e/setup.py` there and
  `python e2e/check.py https://staging.yourdomain.com/api` against a staging copy of the site (never production)
- [ ] Manual browser pass on a phone and a desktop: sign up, search, cart, checkout (COD; online if enabled), order
  page, rider app (camera for the proof photo, location), dashboard, reports, business assistant
- [ ] If Razorpay is enabled: one real low-value payment and refund in live mode; the webhook arrives (dashboard
  shows the payment confirmed without the browser)
- [ ] SMTP: a password-reset email and an order email arrive; spam folder checked
- [ ] `run_jobs` cron runs (Notifications → Delivery log shows sent emails; no stuck pending jobs)
- [ ] Real catalogue entered (prices, MRP, GST/HSN, stock, photos) and the demo data not loaded

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "Incomplete response received from application" / 500 on every request | Check the Passenger log (`~/boltrun_api/stderr.log` or the panel's log). Usually a missing env var (`DJANGO_SECRET_KEY`) or `pip install` not run inside the app's virtualenv |
| `ImproperlyConfigured: PAYMENT_PROVIDER=mock in production` | Intended safety guard. Set `PAYMENT_PROVIDER=razorpay`, or `none` (COD only); `ALLOW_MOCK_PAYMENTS_IN_PROD=true` on staging only |
| `Error loading MySQLdb module` | `pip install -r requirements/mysql.txt` in the app's virtualenv |
| `Access denied for user` | Use the full cPanel-prefixed DB name and user; grant privileges; URL-encode the password |
| `DisallowedHost` | Add the hostname to `DJANGO_ALLOWED_HOSTS` |
| Browser CORS error | Add the exact frontend origin (scheme + host, no trailing slash) to `CORS_ALLOWED_ORIGINS` |
| SPA routes 404 on refresh | `.htaccess` wasn't uploaded (hidden file) or `mod_rewrite` is disabled |
| Admin has no CSS | Run `collectstatic`, then restart the app |
| Code changes not visible | Restart the app (`touch tmp/restart.txt`) |
| Redirect loop after enabling SSL | `SECURE_SSL_REDIRECT=false` (let Apache redirect) |
| `health` returns `"database":"unavailable"` (503) | DB credentials or host wrong, or the DB is down. Check the log for the request ID shown in the `X-Request-ID` header |
| Checkout says "We don't deliver to PIN … yet" for an address you serve | No active delivery zone covers it: add the PIN to a zone's PIN codes or increase the radius; check the store is active, accepts orders and has coordinates (§2a) |
| Only "Standard delivery" is ever offered | The reason is in `fast_unavailable_reason`: no rider available (set "Own riders" or put a verified partner online), store closed (opening hours), zone has fast delivery off, or the calculated time is over the cutoff |
| Map in the address form stays grey | Tiles blocked: allow `tile.openstreetmap.org` in the CSP `img-src`, or set `VITE_MAP_TILE_URL` and rebuild |
| Processes killed / slow | Plan resource limits (§0 #10). Lower Passenger workers; keep `LLM_PROVIDER=none` on shared hosting |
