# ZuuVi catalogue import v1

This is a create-only, supervised import. It creates PENDING products using existing product, pricing, image and inventory services. Approval to execute never approves publication. No category, brand, tag, store or unsupported specification is inferred or created. No browser request starts execution.

## Start here

1. Download the header-only template. Keep all 25 columns in order, including optional columns.
2. Select your authorized existing store. Enter its exact store code on every row. Use verified product names, categories, packs, prices and filenames.
3. Upload a UTF-8 CSV. Review errors by data-record number, starting at 1. Invalid CSV needs a corrected new upload; no partial-valid import option exists.
4. Give the matching photos to the operator through your agreed handoff. There is no browser folder-path field or remote image URL import. The operator prepares and validates them under private staging.
5. Review every preview page, including photos/primary selection and any stock/pricing actions. An authorized manager approves the exact displayed fingerprint. The page then says “Import approved — Awaiting operator”.
6. The operator explicitly executes. Refresh shows durable outcomes and last actual activity. Download the row report. Failures expose safe codes, not filesystem paths or raw exceptions.

The sample CSV is illustrative only. Its categories must already exist exactly as written, and its placeholder store code must be replaced. Example prices and packs are not approved real catalogue data. Both opening-stock cells are deliberately blank. Blank cells create no inventory movement.

An illustrative stock action, only after a verified physical count and appropriate permission, is `opening_stock=3.000` with `opening_stock_reason=Illustrative counted opening balance`. This is an explanation, not a recommendation for your stock. Never copy an example count into real inventory without verification.

## CSV contract

Required values: `store_code`, `external_sku`, `name`, `category_path`, `unit`, `unit_value`, `store_price`. All other values may be blank under the pairing rules below. All 25 headers remain mandatory and ordered.

```csv
store_code,external_sku,name,description,category_path,brand_slug,tag_slugs,unit,unit_value,store_price,profit_margin_type,profit_margin,discount_type,discount_value,manufacturing_date,expiry_date,low_stock_threshold,image_1,image_2,image_3,image_4,image_5,primary_image_index,opening_stock,opening_stock_reason
```

- `external_sku`: trim surrounding whitespace, retain case, max 64 characters. Unique within this store. Name max 200 characters. Description is ordinary escaped text.
- `category_path`: exact existing active target category, full hierarchy separated by ` / `. Ambiguous paths are errors. No silent rename, reparenting or substitution. Optional brand_slug/tag_slugs refer to existing active records. Separate distinct tags with `|`.
- `unit`: PIECE, PACK, BOX, DOZEN, KG, GRAM, LITER, ML or METER. Required unit_value is non-negative Decimal with 12 total digits / 3 decimal places. No inferred conversion.
- `store_price`: required non-negative Decimal, 12 digits / 2 decimals. Blank does not mean zero. No currency symbols, grouping, exponent notation, NaN, Infinity or rounding excess precision.
- `profit_margin_type` and `profit_margin`: both blank or both present; type FIXED/PERCENTAGE. Optional discount_type/discount_value must be paired and require management pricing. Existing pricing limits apply. Only authorized management-origin requests may contain these four values; even numeric zero is forbidden for merchants. No selling/final-price input exists; the backend calculates it.
- `manufacturing_date`, `expiry_date`: optional ISO YYYY-MM-DD; expiry on/after manufacture. Past expiry is flagged for review and existing customer visibility still applies.
- `low_stock_threshold`: optional non-negative Decimal (12,3), blank zero. It never changes stock.
- `image_1`…`image_5`: exact flat JPEG (.jpg/.jpeg), PNG or WebP filenames, including letter case. Fill contiguously from image_1. No URL, slash, backslash, colon, control character, traversal, symlink or case collision. Duplicate filenames or identical content twice within a product are errors. Sharing an image across distinct products is allowed.
- `primary_image_index`: 1…number of images; blank picks the first. Blank is required with no images. Missing photos are visible warnings; publication still requires normal review.
- `opening_stock` and `opening_stock_reason`: both blank or positive Decimal (12,3) plus nonblank reason of at most 500 characters. Requires inventory permission for every responsible participant. Uses the existing opening-stock service, once per created product.

Limits: CSV 5 MiB; at most 1,000 data records; 25 values per record; each cell at most 100,000 characters. UTF-8 BOM supported. Reject malformed quoting, non-UTF-8, NULs, missing/duplicate/reordered/extra headers. A quoted multiline description is one record. Original bytes are preserved and hashed. Reports neutralize spreadsheet formula prefixes and tabs/newlines; do not use the report as a new import template.

Images: at most five per product, 5 MiB per file, 2 GiB total distinct content per prepared job. Content and extension must match existing image validation; decompression-bomb warnings are rejected. Preparation reads one bounded file at a time; execution holds at most five bounded image byte buffers (25 MiB) for the current product, plus bounded CSV/preview data and decoder overhead.

## Permissions and ownership

All grants are Django Group/Permission grants. No automatic grants, duplicate permission system, model admin editing or history deletion are added. Super Admin must satisfy the existing role/staff/superuser gate; Admin must satisfy the management gate. Customers have no importer access.

| Action | Management | Store user |
|---|---|---|
| Template/sample/instructions | add_importjob or view_importjob | Same, active assigned membership/store |
| Upload | add_importjob + view_importjob + add_product | add_importjob + view_importjob; assigned active store |
| Job/list/image/report | view_importjob + view_product | view_importjob; own-created job in current assigned store |
| Approve | approve_importjob + view_importjob + add_product | Never |
| Prepare/execute/resume/status command | execute_importjob + view_importjob + add_product | Never |

Import and product grants are under `catalog`. Management scope follows existing global catalogue permissions. No new admin/store assignments exist. Pricing previews are redacted without `catalog.manage_product_pricing`; reports contain outcomes and identities, never pricing. Private thumbnails repeat job authorization and use `private, no-store` / `nosniff`, never public storage URLs.

Creator, approver and actual operator must each retain requested capabilities. Management pricing requires manage_product_pricing for all three; merchant role cannot price even if granted it. Opening stock requires creator membership.can_manage_inventory or management inventory.adjust_inventory, plus inventory.adjust_inventory for approver/operator. Reload permissions at approval, claim, each row and before commit. Revocation pauses remaining work; committed rows remain. Self-approval is allowed for an otherwise entitled manager. The shell operator must be trusted: --actor identifies the accountable active management username and is not a password authentication mechanism.

## Private staging and operator runbook

`CATALOG_IMPORT_ROOT` is opt-in; empty disables preparation/execution. Configure an existing absolute mode-0700 directory separate from repository source, MEDIA_ROOT, STATIC_ROOT and STATICFILES_DIRS. It must not be publicly served. Web preview and executor must use the same database and bundles.

```text
<private root>/incoming/delivery-01/front.png
<private root>/incoming/delivery-01/back.png
<private root>/snapshots/<bundle UUID>/<sha256>.png
```

Use a direct PostgreSQL session, not transaction pooling. This command intentionally requires an operator; no task queue or implied background worker is added. Example placeholders must be replaced locally:

```text
python manage.py catalog_import prepare --job JOB_UUID --actor AUTHORIZED_USERNAME --image-dir /absolute/private/root/incoming/delivery-01
python manage.py catalog_import status --job JOB_UUID --actor AUTHORIZED_USERNAME
```

After web review and explicit approval:

```text
python manage.py catalog_import execute --job JOB_UUID --actor AUTHORIZED_USERNAME
python manage.py catalog_import resume --job JOB_UUID --actor AUTHORIZED_USERNAME
```

A hard-killed process may leave a RUNNING/PREPARING lease. Inspect status and last activity. Wait until its five-minute lease expires, establish that the prior process/session is gone, then use `resume --reclaim-stale` (or `prepare --reclaim-stale` for unapproved preparation). A stale clock alone cannot authorize takeover: the command must also acquire the session advisory lock and issue a new fencing token. No force-unlock or replacement-input flags exist. Do not manually edit import rows or approvals.

Missing staging displays unavailable/awaiting preparation. Missing/invalid images can be corrected before successful preparation and retried. READY inputs are frozen; changing prepared or approved content requires a new job and new approval. Source-folder changes after preparation do not alter the immutable bundle. Changed snapshot bytes, CSV, taxonomy identity/path or approval hashes block execution.

## Transactions, deduplication and recovery

Signed upload nonces reuse the same owned job for a repeated POST; changed bytes/store under the same nonce conflict. Identical prepared creator/store/CSV/reference/image fingerprints become DUPLICATE stubs with no inherited approval. Different requesters have independent approval contexts.

Source identity is original store/external_sku on the canonical SUCCEEDED ImportRow receipt. Deterministic per-source transaction advisory locks serialize competing jobs. Matching normalized intent resolves the prior receipt even after authorized manual Product.sku/name edits, preserving those edits. Changed intent, unrelated current SKU occupation or inconsistent product ownership is a conflict. No overwriting products, attaching additional images or topping up existing inventory occurs.

An operator holds a PostgreSQL session advisory lock and a durable lease. All writes check its fencing token. If the captured connection closes/fails or is replaced, stop; never auto-reconnect and continue. Each product has its own transaction, holding job/row/source locks. Product creation, optional backend pricing, image rows, optional opening-stock transaction and successful import receipt commit together. There is no whole-job transaction. DB failures are handled only after rollback. Only a specific Product unique-SKU race is eligible for matching-receipt reclassification; unrelated integrity errors remain failures.

RUNNING attempts are durable before product work. Ctrl-C/SIGTERM rolls back an in-progress row or pauses after an already committed row. Abrupt death may leave an unresolved RUNNING attempt. Explicit resume skips terminal receipts and safely retries uncommitted rows. Ordinary conflicts produce COMPLETED_WITH_ERRORS; storage outages, changed inputs and revocation pause further work. Counts derive from receipts, not cached percentages.

Storage is not transactional. A failed/killed attempt may leave unreferenced objects even though product/image/inventory DB rows rolled back. Never physically delete uploaded objects during rollback. Warnings identify possible orphans; a later successful retry does not prove there were no orphan objects. Physical cleanup is separate supervised work, not included here.

## Local validation and hosted prerequisites

Run catalog.tests_import_contract, tests_import_files, tests_import_services, tests_import_permissions, tests_import_views and tests_import_command against isolated PostgreSQL and private temporary media/staging. Include concurrency, receipt/stock/image reconciliation, forced failures, permission changes and interrupted/resumed jobs. Rehearse independent 10/50/1,000-row synthetic inputs. Then run the full regression suite, Django checks, migration drift/plan, isolated static build and whitespace checks. Browser acceptance covers downloads, invalid upload, prepared previews, approval, awaiting operator and results, with responsive checks.

Shared durable staging for a hosted deployment is a separate requirement. This local batch does not prove Railway/import worker operation, transaction-pool compatibility, hosted disk capacity, backup/retention, or operational staffing. Do not infer production readiness from synthetic imports. Real catalogue/store mappings/prices/photos/counts require user verification. Retain Batch A/B Safari, real network-interruption, accessibility and staff acceptance checks on the release checklist.
