# Zuvi — agent instructions

Read `AGENTS.md` first (store isolation, pricing, stock and audit rules still apply). This file adds the API/React layer.

## Layout
Two independently runnable applications in one repository:
- `backend/` — Django project + DRF API at `/api/v1/` (`config/api_urls.py`, `catalog/api/`, `accounts/api.py`).
- `frontend/` — React + TypeScript (strict) + Vite admin app. Storefront, cart, orders, store portal remain Django templates.
- Image pipeline: `catalog/image_pipeline.py`. Excel import: `catalog/product_import/`. Docs: `docs/`.

## Rules
- Inspect before changing. Never reset, drop or recreate a database; migrations stay additive. Ask before destructive operations.
- API views stay thin: call services (`create_product`, `update_product`, `mutate_product_images`, …). Never accept `final_price`, `selling_price` or `stock_quantity` from clients; stock goes through the inventory service.
- Every product photo goes through `image_pipeline.prepare_upload` (manual, API and import). Do not add a second path.
- Import: preview never writes products; commit re-validates and is idempotent. Keep SSRF/ZIP/formula protections intact.
- No secrets, tokens or user data in browser storage; session is the HttpOnly cookie, CSRF header on unsafe requests.
- Never claim a test, load result or deployment was run unless it was; report blockers honestly.
- Files here use CRLF in many places — preserve each file's existing line endings.

## Commands
```bash
cd backend && python manage.py test --parallel 4         # needs PostgreSQL (DATABASE_URL)
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
cd frontend && PW_CHROMIUM_PATH=… npm run e2e            # needs Django (throwaway SQLite, backend/scripts/e2e_seed.py) + Vite
cd backend && locust -f loadtests/locustfile.py …       # see docs/performance-testing.md (throwaway DB only)
```
