# Architecture

```
Clients (React admin today; customer / store / partner apps to come) ──/api/v1──▶ Django + DRF ──▶ PostgreSQL (SQLite for local only)
                                                                                   ├──▶ public media storage (product images)
                                                                                   └──▶ private storage (delivery evidence, attachments)
```

The backend is a **pure API**: the Django-rendered storefront, cart, checkout, orders, customer and store portal pages, forms and templates were removed. Only Django admin, health checks and the API docs render HTML. See [platform-api.md](platform-api.md) for the order, delivery, evidence, review, support and notification workflows, and for the known limitations.

| Area | Status |
| --- | --- |
| Customer, store, delivery-partner, support and admin workflows | REST endpoints under `/api/v1/` (`platform_api`, `deliveries`, `reviews`, `feedback`, `support`, `notifications`). |
| Product management and bulk Excel/CSV import | API plus the React admin in `frontend/`. |
| Image pipeline | Shared `catalog/image_pipeline.py`, used by manual upload, the API, import, evidence and attachments. |
| Authentication | Django users; session+CSRF for browsers, DRF tokens for mobile. |

## Repository layout

```
backend/    Django project + REST API (own requirements.txt, manage.py, railway.toml, tests)
frontend/   React + Vite admin app (own package.json, tests, Playwright)
docs/       shared documentation
```

The two applications share nothing at build time; they communicate only through `/api/v1/` over HTTP.

## Backend layout (`backend/`)

- `config/api_urls.py` mounts `/api/v1/` (auth, OpenAPI schema/docs, catalog).
- `catalog/api/` — permissions, pagination, serializers, views, urls. Views are thin; all writes call the existing services (`create_product`, `update_product`, `mutate_product_images`, …) so pricing, audit logs, store isolation and stock rules are enforced in one place. The API never accepts `final_price`, `selling_price` or `stock_quantity`.
- `catalog/image_pipeline.py` — validation, EXIF orientation, metadata/GPS stripping, resize, re-encode, hashing, thumbnails.
- `catalog/product_import/` — columns, template, parser, validator, ZIP/URL images, service (preview/commit), error reports.
- `catalog/models.py` — `ProductImage` gained `thumbnail`, `content_hash`, `width`, `height`, `file_size`; new `ProductImportBatch`. Migration `0013` is additive.

## Frontend layout (`frontend/`)

`src/app` (providers + router, lazy routes) · `src/pages` · `src/features/auth` · `src/components` · `src/services` (typed API calls) · `src/lib/api.ts` (axios, CSRF, error mapping) · `src/styles` (Tailwind v4 tokens).

## Permissions

The API reuses `user_has_catalog_permission`: Super Admins have everything; Admins need Django's `catalog.view/add/change_product`. Users without portal access get 403. Stores are isolated exactly as in the existing services.
