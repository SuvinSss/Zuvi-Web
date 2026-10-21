# Zuuvi Django admin guide

The Django admin at `/admin/` (for example `http://127.0.0.1:8010/admin/`) is the back-office for the owner and trusted staff.
It is separate from the REST API (`/api/v1/`) and from the React app. Nothing here replaces either of them.

## 1. What was chosen and why
Native Django admin (Django 5.2) plus a small theme. No third-party admin package was added.
* The project already had hardened admin classes (orders, inventory, catalog, stores, accounts) and tests for them; a theme package would have
  had to be reconciled with those.
* Customisation is isolated: `backend/templates/admin/` (template overrides), `backend/static/admin/zuuvi/admin.css` (green theme, light and dark),
  `backend/core/admin_site.py` (navigation grouping and dashboard), `backend/core/admin_base.py` (shared read-only and bulk-action helpers).

## 2. Dependencies and settings
* No new Python packages. `requirements.txt` is unchanged.
* `config/settings.py`: `django.contrib.admin` is replaced by `core.admin_config.ZuuviAdminConfig` (same admin, custom site class), and `TEMPLATES[0]["DIRS"]`
  now contains `backend/templates`.
* No migrations were needed; no model changed.
* One service was extracted so the API and the admin share one rule set: `deliveries.services.decide_partner` (approve / reject / suspend a partner).
  The API response contract is unchanged (checked by tests).

## 3. Run it
```bash
cd backend
python manage.py migrate
python manage.py runserver 8010        # http://127.0.0.1:8010/admin/
```
Production: run `python manage.py collectstatic --noinput`; WhiteNoise serves the theme from `staticfiles/`.

## 4. Accounts and permissions
* Create the first owner: `python manage.py createsuperuser` (the command sets role `SUPER_ADMIN`, staff and superuser together).
* Only **ADMIN** (staff, not superuser) and **SUPER_ADMIN** (staff + superuser) accounts can use the business pages. A support agent, store user, delivery partner or customer is
  refused even when marked "staff" and given permissions.
* Creating and editing users, groups and admin profiles is **Super Admin only**.
* Create a staff admin: Users → Add user, role **Admin**, tick *Staff status*, leave *Superuser* off.
* Give them access with Groups (Users → Groups). Suggested groups:
  * *Viewer*: every `view_…` permission. They can look at everything but every action menu is empty.
  * *Operations*: *Viewer* + `change_deliverypartner`, `change_delivery`.
  * *Care*: *Viewer* + `change_review`, `change_ticket`, `change_complaint`, `change_feedback`.
* On the new pages `view_…` permission opens the pages, and `change_…` permission unlocks that model's bulk actions. Permissions are enforced on the server for direct URLs and form posts, not only by hiding menus.

## 5. How the navigation is organised
| Section | Pages |
|---|---|
| Operations | Orders, Store orders, Deliveries, Delivery partners, Delivery assignments, attempts, evidence, Location pings, order items and history, pickup locations |
| Customer care | Tickets, Complaints, Ticket messages, Feedback, Reviews, Review reports, Rating aggregates |
| Stores and catalog | Stores, Store users, Store categories, Products, Categories, Brands, Tags, Product images, status and price history, Inventory transactions, Purchase entries |
| People and access | Users, Customers, Customer and other addresses, Admin profiles, Groups, Carts |
| Records and notices | Audit events, Admin audit log, Notifications, Notification preferences |

The Dashboard shows live counts from the database (nothing hard-coded): orders awaiting action, deliveries waiting or flagged, partners/stores/products awaiting approval, open tickets,
unresolved complaints, customers, active stores, approved and online partners, total orders, orders in progress, active and completed deliveries.
Each card links to the matching filtered list; a card is hidden if you cannot view that list. The page runs about a dozen aggregate queries and no row lists.

## 6. Working with records
* **Search** box and **filters** (right side) are on every list; dates have a drill-down bar.
* **Delivery partners**: filter by status; actions *Approve*, *Reject…* (reason needed), *Suspend…* (reason needed). Suspending also takes the partner offline.
* **Deliveries**: search by order number or partner; actions *Approve a retry* (new attempt + new OTP) and *Cancel…* (reason). The page shows assignments, attempts, status history and evidence summary.
* **Orders**: view only; use the app (admin area of the React site) for status changes and cancellations, which apply the order lifecycle rules.
* **Stores and products**: the existing admin screens are unchanged (edit forms, status history, approvals).
* **Reviews**: filter by status/rating; actions *Hide…*, *Reject…* (reason), *Restore*. Replies and reports appear inline.
* **Feedback**: actions mark in review or closed. **Tickets**: actions *Assign…* (choose a support agent) and *Escalate…*. **Complaints**: *Assign…*.
  Customer-visible replies and private staff notes sit in the same inline, separated by the **Internal** column.
* Every bulk action shows a confirmation page, runs each record in its own transaction, and reports skipped records and why. Nothing is skipped silently.

## 7. What is deliberately restricted
* No add, edit or delete on deliveries, partners, reviews, feedback, tickets, complaints, notifications, audit events or evidence. Their rules (state machines, SLA clocks, notifications, audit) live in services, and the admin calls those services.
* Not shown anywhere: delivery OTP values, raw GPS coordinates (partner, delivery, GPS pings), notification message bodies and payloads, passwords and tokens.
* Evidence photos and support attachments are in private storage; the admin lists name, type and size only. Open them through the app, which checks permissions.
* No bulk delete anywhere on the new pages.
* Not registered on purpose: Google sign-in identities, photo-import and product-import batch internals, purchase lines (shown inside their purchase entry).

## 8. Troubleshooting
* **Login redirects back to the form**: the account must be active, *Staff status* ticked, and role Admin or Super Admin. `createsuperuser` sets this for you.
* **403 on a page**: the account lacks that model's `view_…` permission (add it through a Group), or it is not an Admin / Super Admin.
* **Plain, unstyled admin**: run `collectstatic` (production) or use `runserver` with `DJANGO_DEBUG=1` (development); check the browser can load `/static/admin/zuuvi/admin.css`.
* **An action does not appear**: you need that model's `change_…` permission.

## 9. Verification (what was run)
* `python manage.py check`: no issues.
* 20 new admin tests (`deliveries/tests_admin.py`): login page, anonymous and wrong-role refusal, permission enforcement on direct posts, read-only registration, list/detail rendering of every new model, search and filters, dashboard numbers and query count, no OTP/coordinates/notification body in pages, bulk actions through services (including reason-required and skipped records), API contract for partner decisions.
* Full backend suite on PostgreSQL: see the result in the final report (not claimed here until run).
* Rendered in headless Chromium against a throwaway SQLite database: dashboard and nine list pages at 1280 px and 390 px, no horizontal overflow, no page errors or failed requests.

## 10. Known limitations
* Not tested in a real phone or in Safari/Firefox; no screen-reader pass.
* The throwaway test data is tiny, so list performance on large tables is reasoned (indexes, `select_related`, bounded pages) but not load-tested.
* Complaint escalation, resolve and reject, ticket replies and status changes are not offered as bulk actions; use the support area of the app.
* Order status changes are not in the admin (they remain in the app so the lifecycle rules apply).
* Model plural names are Django defaults ("Delivery evidences").
