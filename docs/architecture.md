# Architecture

```
Browser ── React SPA (frontend/, Vite) ──/api/v1──▶ Django + DRF ──▶ PostgreSQL (SQLite for local only)
   │                                                    │
   └── storefront, cart, orders, store portal ──────────┘   (unchanged Django templates)
                                                        └──▶ media storage (filesystem locally, S3 hosted)
```

## What changed, what did not

| Area | Status |
| --- | --- |
| Storefront, cart, checkout, orders, store portal, inventory, Django admin | **Unchanged** Django templates and views. |
| Product management (list, create, edit, photos) | New React screens on `/api/v1/products/…`. The classic management screens still work. |
| Bulk Excel/CSV import | New (API + React). |
| Image pipeline | New shared module `catalog/image_pipeline.py`, used by manual upload, the API and import. |
| Authentication | Same Django users and sessions; a thin JSON layer in `accounts/api.py`. |

This is a **phased** migration: the API plus an admin SPA first. Moving the storefront/cart/orders to React is future work and is *not* done.

## Backend layout

- `config/api_urls.py` mounts `/api/v1/` (auth, OpenAPI schema/docs, catalog).
- `catalog/api/` — permissions, pagination, serializers, views, urls. Views are thin; all writes call the existing services (`create_product`, `update_product`, `mutate_product_images`, …) so pricing, audit logs, store isolation and stock rules are enforced in one place. The API never accepts `final_price`, `selling_price` or `stock_quantity`.
- `catalog/image_pipeline.py` — validation, EXIF orientation, metadata/GPS stripping, resize, re-encode, hashing, thumbnails.
- `catalog/product_import/` — columns, template, parser, validator, ZIP/URL images, service (preview/commit), error reports.
- `catalog/models.py` — `ProductImage` gained `thumbnail`, `content_hash`, `width`, `height`, `file_size`; new `ProductImportBatch`. Migration `0013` is additive.

## Frontend layout (`frontend/`)

`src/app` (providers + router, lazy routes) · `src/pages` · `src/features/auth` · `src/components` · `src/services` (typed API calls) · `src/lib/api.ts` (axios, CSRF, error mapping) · `src/styles` (Tailwind v4 tokens).

## Permissions

The API reuses `user_has_catalog_permission`: Super Admins have everything; Admins need Django's `catalog.view/add/change_product`. Users without portal access get 403. Stores are isolated exactly as in the existing services.
