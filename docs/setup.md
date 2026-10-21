# Local setup

Requirements: Python 3.13, Node 22+ (Node 24 recommended), PostgreSQL 16 (optional locally).

## Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set DJANGO_SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver      # http://127.0.0.1:8000
```

With no `DATABASE_URL`, **local** runs (`DJANGO_ENVIRONMENT=local`) fall back to SQLite at `data/zuvi.sqlite3` (override with `SQLITE_PATH`). Hosted environments still require PostgreSQL. SQLite is a convenience: search uses plain `contains` matching (no trigram typo tolerance) — use PostgreSQL to see production behaviour. See `database.md`.

## Frontend

```bash
cd frontend
npm install
npm run dev                     # http://127.0.0.1:5173 (from the frontend/ folder)
```

The dev server proxies `/api`, `/media`, `/management` and `/static` to Django (`VITE_DEV_BACKEND_URL`, default `http://127.0.0.1:8000`), so the session cookie is same-origin and no CORS setup is needed. Sign in with a Super Admin or Admin account.

## Checks

```bash
# backend (run inside backend/)
python manage.py test --parallel 4          # PostgreSQL via DATABASE_URL
# frontend
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
# browser tests (needs Django + Vite running, see docs/testing in frontend/e2e)
python manage.py migrate && python manage.py shell < scripts/e2e_seed.py   # with SQLITE_PATH=/tmp/e2e.sqlite3
PW_CHROMIUM_PATH=/path/to/chromium npm run e2e
```

## Environment variables added

| Variable | Default | Purpose |
| --- | --- | --- |
| `SQLITE_PATH` | `data/zuvi.sqlite3` | Local-only SQLite file when `DATABASE_URL` is unset. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` (local) | Origins allowed to call `/api/v1/` with credentials. Required if the SPA is on another origin. |
| `DJANGO_SESSION_COOKIE_AGE` | 14 days | Session lifetime in seconds. |
| `API_THROTTLE_USER` / `API_THROTTLE_LOGIN` / `API_THROTTLE_IMPORT` | `600/min` / `10/min` / `30/hour` | DRF throttle rates. |
| `PRODUCT_IMAGE_*`, `PRODUCT_IMPORT_*` (Django settings) | see `product-images-and-imports.md` | Size/pixel/row/ZIP limits. |
| `VITE_API_BASE_URL`, `VITE_DEV_BACKEND_URL` (frontend) | `/api/v1`, `http://127.0.0.1:8000` | See `frontend/.env.example`. |
