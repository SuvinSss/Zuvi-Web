# Zuuvi platform API

Zuuvi is a pure Django REST Framework backend. Every customer, store, delivery-partner, support and admin
client talks to `/api/v1/`. Machine-readable reference: `/api/v1/schema/` (OpenAPI) and `/api/v1/docs/` (Swagger).
This page covers how the pieces fit together and what is, and is not, verified.

## 1. Architecture

```
clients (React admin today; customer / store / partner apps later)
        │  JSON over HTTPS — session+CSRF (browser) or Token (mobile)
        ▼
config/api_urls.py ── platform_api/ (auth, public, customer, store, admin)
        │            ├─ deliveries/  reviews/  feedback/  support/  notifications/
        │            └─ catalog/api, accounts/api (product management, Excel import)
        ▼
service layer  (orders, inventory, catalog, deliveries, reviews, support …)   ← all business rules
        ▼
PostgreSQL  +  media storage (public product images)  +  private storage (evidence, attachments)
```

* Views are thin: authenticate → resolve the caller's own record from `request.user` → call a service → serialise.
* One error shape (`core/exceptions.py`): `{"detail": "…"}` or `{"field": ["…"]}`. Unhandled errors return a generic 500 and are logged, never echoed.
* Roles: customer, store owner/staff, delivery partner, support agent, support supervisor, admin, super admin
  (`accounts.models.Role`). Admin screens use Django permissions (`user_has_order_permission`, catalogue permissions).
* Ownership: customers, stores and partners can only reach their own records. Cross-owner ids return 404.
* `core.AuditEvent` is an append-only log (no update/delete in the model layer) for security-relevant actions.

## 2. Authentication
| Client | Flow |
|---|---|
| Admin SPA | `POST /auth/login/` (management accounts only), HttpOnly session cookie, `X-CSRFToken` on unsafe requests |
| Any role, browser | `POST /auth/signin/` (session + CSRF) |
| Mobile | `POST /auth/token/` → `Authorization: Token …`; `POST /auth/token/revoke/` logs out |
| Sign-up | `/auth/register/` (customer), `/auth/partner-register/` (delivery partner, starts `PENDING`) |
| Passwords | `/auth/password/change|reset|reset/confirm/` (reset never reveals whether an email exists) |
Login (10/min), register (10/hour) and location (120/min) endpoints are throttled; rates are environment-configurable.

## 3. Order lifecycle
`Order` (customer) → one `StoreOrder` per store → `OrderItem`. A StoreOrder moves
`PENDING → ACCEPTED → PROCESSING → READY → COMPLETED` (or `REJECTED`/`CANCELLED`); the parent Order status is derived
(`sync_order_status_from_store_orders`). Every change writes a history row with actor and reason.
Checkout is idempotent: send an `Idempotency-Key` header and a repeated request returns the same order.
Prices, totals and stock are computed server-side; clients send only product ids, quantities and an address id.

## 4. Delivery
```
PENDING_ASSIGNMENT ─offer→ OFFERED ─accept→ ACCEPTED ─arrive-store→ AT_STORE ─pickup→ IN_TRANSIT ─arrive→ ARRIVED ─complete→ DELIVERED
        ▲                     │ reject/expire        │ release                                      │            │
        └─────────────────────┴──────────────────────┘                                              └─ fail ─→ FAILED ─retry→ PENDING_ASSIGNMENT
                                                      any open state ── cancel ──→ CANCELLED
```
* A Delivery is created when the store marks the StoreOrder `READY` (`on_store_order_ready`).
* **Assignment:** nearest approved, online, free partner by haversine distance (`auto_assign`); an admin can assign by hand.
  An offer expires after `DELIVERY_OFFER_TTL_SECONDS` (default 120). After `DELIVERY_MAX_REJECTIONS` (5) automatic offers stop and an admin must step in.
* **Pickup evidence:** the store confirms handover and/or the partner uploads a pickup photo (`/deliveries/{id}/pickup/`).
* **Completion requires evidence:** at least one delivery photo (plus the OTP when `DELIVERY_REQUIRE_OTP` is on). Without it the call is refused and the order stays open. `DELIVERY_ENFORCE_LOCATION_TOLERANCE` additionally checks the partner is within `DELIVERY_LOCATION_TOLERANCE_M` of the address.
* **OTP:** derived by HMAC from a per-delivery nonce and `SECRET_KEY`; it is never stored in plain text. Wrong attempts are counted even though the request fails, and lock after `DELIVERY_MAX_OTP_FAILURES`.
* **Failure and retry:** `fail` needs a reason (`CUSTOMER_UNAVAILABLE`, …; `OTHER` needs a note) and creates a `DeliveryAttempt`. An admin can retry up to `DELIVERY_MAX_ATTEMPTS`; each attempt needs fresh evidence.
* **Management shortcut:** the admin "mark completed" path refuses a StoreOrder whose Delivery is not `DELIVERED`.
  Orders created before the delivery module have no Delivery row and can still be completed by an admin (see limitations).

### Tracking
* Partner posts `POST /deliveries/{id}/location/` (rate-limited: minimum interval `DELIVERY_MIN_PING_INTERVAL_SECONDS`, accuracy cap `DELIVERY_MAX_PING_ACCURACY_M`, coordinates validated).
* Customer reads `GET /orders/{id}/tracking/`: status, timeline, partner first name and vehicle type, last known position with `age_seconds`, and `is_stale` once no ping arrived for `DELIVERY_STALE_SECONDS` (90).
* **ETA is `null`.** No routing provider is integrated; the API does not invent an estimate.
* Admin/partner history: `GET /deliveries/{id}/tracking-history/` (partner sees only their own).

## 5. Evidence and private storage
* Photos go through `core.uploads.clean_image` → `catalog.image_pipeline.prepare_upload`: content decoded (not trusted by name or content-type), EXIF orientation applied, all metadata including GPS removed, re-encoded, random file name. PDFs (attachments only) are accepted by magic bytes and size.
* Files are stored in `STORAGES['private']` (`backend/private_media/` locally, a private bucket prefix with `default_acl=private` on S3). They are **never** under `MEDIA_URL`.
* Access: `GET /evidence-photos/{id}/file/` and `GET /support/attachments/{kind}/{id}/file/` check the caller (owner, assigned partner, store of that order, support staff, admin) and stream with `Cache-Control: private, no-store` and `nosniff`.
* Retention/backup: nothing deletes evidence automatically. Back up the private bucket/volume together with the database; define retention per your legal requirements before go-live. Not implemented: automatic purge.

## 6. Reviews and ratings
* A customer can review a store (and each product) only after that StoreOrder is `COMPLETED`; one review per target per order; rating 1–5; HTML is stripped.
* Customers may edit or withdraw their own review. Stores get one public reply per review and cannot change ratings.
* Moderation (`hide`, `reject`, `restore`) needs a reason and writes an audit event. Users can report a review.
* `RatingAggregate` (average, count, distribution) is recomputed from **published** reviews only, inside the same transaction, so hide/reject/withdraw updates it. Public list endpoints expose only published reviews.

## 7. Feedback, tickets, complaints
* **Feedback** (`/feedback/`): general product/app feedback with staff replies (`internal=true` replies are staff-only), status changes (`NEW`, `IN_REVIEW`, `REPLIED`, `ESCALATED`, `CLOSED`) and escalation to support.
* **Tickets** (`/support/tickets/`): users open tickets (statuses `OPEN`, `IN_PROGRESS`, `WAITING_CUSTOMER`, `RESOLVED`, `CLOSED`); messages with attachments; staff set status/priority, assign, escalate. Internal notes (`internal=true`) and staff events are never serialised for requesters.
* **Complaints** (`/support/complaints/`): formal workflow with statuses `SUBMITTED → UNDER_REVIEW ⇄ INFO_REQUESTED → ESCALATED → RESOLVED / REJECTED → CLOSED` (reopen allowed), escalation to supervisors, evidence attachments and a full timeline.
* **Roles:** support agents see their assigned and unassigned items; supervisors/admins see all, assign, take over and handle escalations.
* **SLA:** due times derive from `created_at` and priority/severity (defaults in `support/sla.py`, overridable via `SUPPORT_TICKET_SLA_HOURS` / `SUPPORT_COMPLAINT_SLA_HOURS`). States: `ok`, `due_soon`, `breached`, `met`, `missed`.
  `send_sla_reminders` notifies once per threshold (`sla_notices`).

## 8. Notifications
`notifications.services.notify()` always creates an in-app notification. Email is attempted after the transaction commits
(`transaction.on_commit`) only when an email backend is configured (`NOTIFICATION_EMAIL_ENABLED` or `EMAIL_HOST`) and the user
has not disabled it; the outcome is stored in `email_status` (`SENT`, `FAILED`, `SKIPPED`, `NOT_REQUESTED`). A mail failure never fails the business operation.
Endpoints: list (`?unread=1`), unread count, mark read, read-all, preferences. Users only ever see their own.

## 9. Scheduled work (not scheduled by the application)
Run these from cron, systemd timers, Celery beat or a platform scheduler. If you do not, the behaviour below does not happen:
| Command | Suggested cadence | Purpose |
|---|---|---|
| `python manage.py process_deliveries` | every minute | expire stale offers, re-offer, sweep unassigned deliveries |
| `python manage.py send_sla_reminders` | every 5–15 minutes | support SLA reminders |

## 10. PostgreSQL deployment
* Set `DATABASE_URL=postgresql://…` (required in production; SQLite is a local fallback only). Run `python manage.py migrate` — all migrations are additive.
* Row locks (`select_for_update`) are used for stock, delivery, ticket and complaint transitions; they are no-ops on SQLite, so concurrency behaviour is only meaningful on PostgreSQL.
* `/health/ready/` checks the database; `/health/live/` does not.

## 11. Known limitations (honest list)
* Email, scheduled reminders and `process_deliveries` depend on your configuration and scheduler; none were exercised against a real mail server or scheduler.
* No routing/maps provider: ETA is `null`, and distance is straight-line (haversine), not road distance.
* GPS tracking was tested with simulated pings only — not with real devices, background-location behaviour or poor networks.
* COD payment collection is not automated by delivery completion.
* Orders that predate the delivery module have no Delivery row; an admin can still complete them without evidence.
* No automatic retention/purge of evidence or attachments.
* Load numbers in `docs/performance-testing.md` are from a single small test machine and are not a capacity guarantee.
* The Django-rendered storefront, cart, checkout and store portal were removed from this branch. Do not deploy this branch to the live site until the replacement clients exist.
