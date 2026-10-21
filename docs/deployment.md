# Deployment

The Django service lives in `backend/` and deploys as before (Railpack + Gunicorn, see README and `backend/railway.toml`). **Set the Railway service's Root Directory to `backend`** — the build, migrate and start commands in `railway.toml` are relative to it. New requirements: `openpyxl`, `defusedxml`, `drf-spectacular`, `django-cors-headers` (in `requirements.txt`); migration `catalog.0013`.

## Serving the React app

`cd frontend && npm ci && npm run build` produces static files in `frontend/dist`. The Django storefront already owns paths such as `/products/`, so the SPA must **not** share a path space with it. Recommended: host `dist/` on a static host under its own subdomain (e.g. `manage.example.com`) and the API on a sibling subdomain, then set:

- `VITE_API_BASE_URL=https://api.example.com/api/v1` at build time,
- `DJANGO_CORS_ALLOWED_ORIGINS=https://manage.example.com`,
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://manage.example.com`,
- HTTPS, `DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True`, and a shared parent cookie domain only if you add that setting deliberately.

Static host must rewrite unknown paths to `index.html` (SPA routing). **This hosting topology is documented but has not been exercised end to end**; only the Vite dev proxy (same-origin) was tested.

## Checklist

- `DATABASE_URL` → PostgreSQL; `DJANGO_ENVIRONMENT` not `local` (SQLite fallback is local-only).
- `MEDIA_STORAGE_BACKEND=s3` with the bucket's own credentials; thumbnails and originals use the same storage.
- Raise `WEB_CONCURRENCY` for load (see `performance-testing.md`). Image processing and imports are CPU-bound inside the request; large imports belong in a background worker if usage grows (not implemented).
- `python manage.py check --deploy` (run in CI).
