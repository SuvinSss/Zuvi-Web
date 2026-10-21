# Product images and Excel/CSV import

## Image pipeline (`catalog/image_pipeline.py`)

One pipeline serves manual upload (Django views), the API and bulk import.

1. **Validate** by content (Pillow decode), not file name: JPEG, PNG, WebP only; ≤ 5 MB; ≤ 25 megapixels. Corrupt, truncated, SVG/HTML/script-disguised files are rejected with a plain message.
2. **Normalize:** apply EXIF orientation, drop all metadata (including GPS), convert to a web format, cap the longest side at 2400 px (never upscale), re-encode.
3. **Hash** the processed bytes (SHA-256). Identical content reuses the stored file name, so duplicates do not create extra blobs.
4. **Thumbnail:** 400×400 WebP, product *contained* (no crop, no upscale) on `#F8FAFC`.
5. **Record** `content_hash`, `width`, `height`, `file_size`, `thumbnail`.

Existing PNG `display_image` generation is unchanged. Deleting a product image removes only the database reference; files are kept (rollback- and dedupe-safe). Use `python manage.py cleanup_product_media` (dry run by default; `--delete`, `--older-than-hours`) to remove unreferenced files deliberately. Photos uploaded before this feature can be given thumbnails with `python manage.py backfill_product_thumbnails [--apply] [--limit N]`.

Tunables (Django settings, all optional): `PRODUCT_IMAGE_MAX_BYTES`, `_MAX_PIXELS`, `_MAX_DIMENSION`, `_THUMBNAIL_SIZE`, `_THUMBNAIL_QUALITY`, `_JPEG_QUALITY`, `_WEBP_QUALITY`, `_BACKGROUND`.

### Fallbacks (the UI never shows a broken image)

1. Uploaded product thumbnail/display image →
2. *(approved brand asset — **not implemented**: no brand-image model exists yet)* →
3. Category-specific placeholder (bundled in the app, no network request) →
4. Generic Zuvi placeholder.

If an `<img>` fails to load, `ProductImage` switches to the placeholder at runtime. Boxes are square and sized up front, so there is no layout shift.

### Brand-aware suggestions

`GET /products/{id}/image-suggestions/` is deliberately **inert** (`available:false`). Suggestions are optional and never required; shipping real ones needs a licensed image source and an approval workflow, because matching on brand alone can attach the wrong product photo. Nothing is downloaded or attached automatically.

## Bulk import

Columns (`store_code, sku, name, category` and `store_price` are required): see the template's **Instructions** and **Reference** sheets. Stock, barcode, tax and variants are intentionally *not* columns — the model has no such fields, and stock must go through the inventory service. Prices are never imported as final prices; `store_price` is the input and the pricing service computes the rest.

Flow: **template → preview → review → confirm**.

- Preview parses the file, validates every row against the live database, stages the files, and stores a `ProductImportBatch`. No product is created.
- Modes: `create` (existing SKU = error), `skip` (existing SKU left alone), `update` (existing SKU updated through `update_product`, audited).
- Commit re-parses and re-validates (data may have changed), locks the batch, and runs in one transaction by default (**all-or-nothing**). "Valid rows only" uses per-row savepoints. A file that was already committed is rejected (409) and a repeated commit returns the stored result — no duplicates.
- Images come from an optional ZIP (`image_file` column) or, only if enabled for the batch, an `image_url`. Rows without an image get the placeholder.
- Errors are reported per row and column in the UI and as downloadable CSV/XLSX (cells starting with `= + - @` are neutralized).

Limits (settings `PRODUCT_IMPORT_*`): 5 MB sheet, 1000 rows, xlsx container ≤ 50 MB uncompressed, ZIP ≤ 50 MB / 500 files / 200 MB expanded, URL timeout 5 s.

### Security controls

Formula cells and `=`/`@`-prefixed text are rejected; XML is parsed with defusedxml; ZIP entries are checked for traversal, absolute paths, symlinks, type, count and expanded size before reading. URL images: http/https only, DNS resolved and every address must be public (loopback, private, link-local, metadata ranges refused), no redirects, size and time caps, and the connected peer IP is re-checked (fails closed). Residual risk: a DNS-rebinding race between resolution and connect is mitigated by the peer check but is not formally eliminated.
