# Zuvi — agent instructions

Read `AGENTS.md` first (store isolation, pricing, stock and audit rules still apply). This file adds the API layer.

## Layout
- `backend/` — **pure Django REST Framework API** at `/api/v1/`. There are no Django-rendered pages, forms or templates any more (only Django admin, health checks and the OpenAPI/Swagger UI render HTML).
  - Domain apps: `accounts`, `catalog`, `cart`, `customers`, `stores`, `inventory`, `locations`, `orders`.
  - Platform apps: `core` (errors, permissions, audit log, private uploads/files, geo), `deliveries`, `reviews`, `feedback`, `support`, `notifications`.
  - `platform_api/` is a URL/view package (not an installed app) with the role-based endpoints: auth, public catalogue, customer, store, admin.
  - Routes are assembled in `config/api_urls.py`.
- `frontend/` — React + TypeScript (strict) + Vite admin app (product management / Excel import). Customer, store and delivery-partner front ends are future clients of the same API and are **not** in this repository.
- Image pipeline: `catalog/image_pipeline.py`. Excel import: `catalog/product_import/`. Docs: `docs/` (start with `docs/platform-api.md`).

## Rules
- Inspect before changing. Never reset, drop or recreate a database; migrations stay additive. Ask before destructive operations.
- API views stay thin: call services (`create_product`, `update_product`, `place_order`, `deliveries.services.*`, …). Never accept `final_price`, `selling_price`, `stock_quantity`, status, totals or ownership ids from clients; stock goes through the inventory service.
- Resolve the caller's customer/store/partner from `request.user` (`core.permissions`). Return 404, not 403, where existence must not leak.
- Every image goes through `catalog.image_pipeline.prepare_upload` (product photos, evidence and attachments via `core.uploads`). Do not add a second path.
- Private files (delivery evidence, ticket/complaint attachments) live in `STORAGES['private']` and are only streamed by authenticated endpoints through `core.files.private_file_response`. Never put them under `MEDIA_URL`. `backend/private_media/` must never be committed.
- An order is never marked delivered without delivery evidence (`deliveries.services.complete_delivery`). The management shortcut refuses orders that have an unfinished Delivery.
- Internal notes and staff-only events are never serialised for customers, stores or partners.
- Import: preview never writes products; commit re-validates and is idempotent. Keep SSRF/ZIP/formula protections intact.
- No secrets, tokens or user data in browser storage; the admin SPA session is the HttpOnly cookie with a CSRF header on unsafe requests. Mobile clients use `/auth/token/`.
- Never claim a test, load result, email, GPS, schedule or deployment was run/working unless it actually was; report blockers honestly.
- Files here mix LF and CRLF — preserve each file's existing line endings.

## Commands
```bash
cd backend && python manage.py test --parallel 4 --noinput   # DATABASE_URL=postgresql://… for the PostgreSQL run; SQLite fallback otherwise
cd backend && python manage.py makemigrations --check --dry-run
cd backend && python manage.py spectacular --file schema.yml --validate
cd backend && python manage.py process_deliveries           # offer expiry / unassigned sweep — needs an external scheduler
cd backend && python manage.py send_sla_reminders           # support SLA reminders — needs an external scheduler
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
cd backend && locust -f loadtests/locustfile.py …           # see docs/performance-testing.md (throwaway DB only)
```
Tests that need PostgreSQL (readiness probe, concurrent image additions) fail on SQLite by design; run them with `DATABASE_URL` set.
