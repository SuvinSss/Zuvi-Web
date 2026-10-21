# Admin approval, store and import workflows

## Stores
* **Create:** Admin → Stores → *Add store* (6-step wizard, `POST /api/v1/admin/stores/`). Needs `stores.add_store`.
* **Status is decided by the server**, never by the client. The request body is a whitelist: `status`, `approved_by`, `verification_status` and similar fields are ignored.
  * *Save draft* → `DRAFT`.
  * Mandatory requirements missing (name, category, phone, owner, contact, location, address…) → `NEEDS_INFO`, with the missing list returned and stored.
  * Complete and actor holds `stores.approve_store` (Super Admin implicit) → `ACTIVE`, approver and time stamped, `creation_source=ADMIN`.
  * Complete but actor cannot approve → `PENDING`.
* **Verification, approval and operational activation are separate.** Documents/GSTIN never verify a store; only `POST …/verify/` does, and it never changes status. Customers can only order when `ordering_enabled` (opening hours set, radius if delivering, accepts orders) – enforced in checkout.
* Location (0,0) means "not set". Commission can only be set by users with approve rights.
* List: filters (status, category, city, type, verification, ordering), URL-held state, sort, pagination, CSV export (formula-safe), bulk actions. Detail has 11 tabs.

## Product import
1. Upload → `POST /api/v1/products/import/preview/`. Headers are matched to known columns through an alias table; unknown/ambiguous headers return `422 needs_mapping` and the mapping screen lets the person choose (or ignore) each column. `stock` and `quantity` are deliberately ignored.
2. Every row is classified **valid**, **incomplete** (only required/lookup values missing – fixable) or **invalid**.
3. Only deterministic fixes are applied: trimmed text, unit synonyms, currency symbols stripped, SKU generated as `AUTO-<name-slug>` when missing (opt-out). Each is listed per row and stored on `Product.generated_fields`. **Prices, tax, stock, barcodes and legal data are never invented or rounded.**
4. Fix a row in place (`PATCH …/rows/<n>/`); corrections are stored as overrides and the batch is re-analysed.
5. Commit is idempotent and per batch. After a partial import, *Retry* imports only the rows not yet created (skip mode) and accumulates the summary. Jobs are listed in Admin → Bulk import jobs and re-opened with `?job=<id>`.

## Approval Center and bulk actions
* Admin → Approval center summarises products, stores (pending and needs-info), delivery partners and reported reviews. Promotions do not exist in this system and are reported as not available.
* `POST /api/v1/admin/bulk/<module>/preview/` returns eligible, blocked (with reasons) and warning records and changes nothing. `…/apply/` requires `confirm`, and `expected_count` when `select_all` is used.
* Select-all across pages resolves ids server-side from whitelisted filters; the count is confirmed before applying. Max 500 records per operation; throttled (60/hour).
* Every record is rechecked and committed in its own transaction at apply time. The result lists successful, skipped and failed records separately.
* Products without a price, image or store cannot be approved; pending/rejected products are never purchasable. Rejection requires a reason. Each operation writes one audit event `bulk.<module>.<action>` (ids and counts, no secrets).

## Permissions
SUPER_ADMIN is implicit; ADMIN needs the Django permission (`stores.add_store`, `stores.approve_store`, `catalog.approve_product`, …). The UI hides actions the API would refuse, but the API is the authority.

## Known gaps
No payment/tax/payout set-up; coordinates are entered by hand (no geocoding); the wizard edits one opening slot per day (API accepts four); customers and orders have no bulk actions; documents/banners use default file storage.
