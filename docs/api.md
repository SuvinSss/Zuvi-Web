# API reference (`/api/v1/`)

Machine-readable schema and Swagger UI: `/api/v1/schema/` and `/api/v1/docs/` (login required).
All endpoints use the Django session cookie; unsafe methods need the `X-CSRFToken` header.
Errors are JSON: `{"detail": "..."}` or `{"field": ["message"]}` (HTTP 400). 401/403 for auth, 404 for missing/other-store objects, 409 for import conflicts, 429 when throttled.

| Method & path | Purpose |
| --- | --- |
| `GET /auth/session/` | `{authenticated, user, csrf_token}`; sets the CSRF cookie. Used to restore the session on page load. |
| `POST /auth/login/` | `{username, password}` → session. Management accounts only. Throttled. |
| `POST /auth/logout/` | Ends the session (204). |
| `GET /products/` | Paginated list. Params: `q`, `status`, `category`, `store`, `brand`, `is_active`, `has_image`, `ordering`, `page`, `page_size` (≤100). |
| `POST /products/` | Create (draft or pending). Prices and stock are *not* accepted. |
| `GET/PATCH /products/{id}/` | Detail / update. |
| `GET /products/meta/` | Stores, categories, brands, tags, units, limits for forms. |
| `POST /products/{id}/images/` | Multipart upload (`image`, `alt_text`, `is_primary`). |
| `DELETE /products/{id}/images/{image_id}/` | Remove the reference (files are retained). |
| `POST /products/{id}/images/{image_id}/primary/` | Make primary. |
| `GET /products/{id}/image-suggestions/` | Optional suggestions; currently returns `available:false` (no licensed source configured). |
| `GET /products/import/template/` | Excel template (Products, Instructions, Reference sheets). |
| `POST /products/import/preview/` | Multipart: `file` (.xlsx/.csv), optional `images_zip`, `mode` (create/skip/update), `all_or_nothing`, `initial_status`, `allow_image_urls`. Nothing is written except a preview batch. |
| `GET /products/import/{uuid}/` | Batch detail. |
| `POST /products/import/{uuid}/commit/` | Apply the previewed import. Re-validates against current data; idempotent. |
| `GET /products/import/{uuid}/errors/?type=csv\|xlsx` | Error report (formula-injection safe). |

Product list items include `image`: `{source: "uploaded"|"fallback", thumbnail_url, display_url, alt_text, width, height, fallback?}`; the UI always renders a placeholder when `source` is `fallback` or the file fails to load.
