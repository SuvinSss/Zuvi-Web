# Zuuvi business admin (React) guide

The owner's day-to-day back-office is the React application under **`/admin`**. It talks only to the REST API; Django's own admin is a technical fallback at `/django-admin/` (see `django-admin-guide.md`).

## 1. Architecture
* Same frontend project as the rest of the site (`frontend/`, React 19 + TypeScript + Vite + Tailwind tokens + TanStack Query). No second frontend and no new UI or chart library; charts are small SVG components (`src/components/charts.tsx`) that also expose a hidden data table for screen readers.
* Shell: `src/layouts/AdminLayout.tsx` (top bar with global search, notifications, profile menu; sidebar badges from `/admin/counts/`) around the shared `DashboardLayout` (collapsible sidebar, foldable groups, mobile drawer). Sidebar state is remembered in `localStorage` (`zuuvi.nav.collapsed`, `zuuvi.nav.closed`) and the app works without it.
* Navigation: `src/app/navigation.ts` (`ADMIN_NAV`). Routes: `src/app/router.tsx`. Pages: `src/pages/admin/`.
* Backend: Django REST Framework in `backend/platform_api/`. Dashboard, customers, export, search and categories live in `platform_api/analytics.py`. No new models, no migrations, no second database.

## 2. Pages (all backed by real endpoints)
| Page | Route | Endpoints |
|---|---|---|
| Dashboard | `/admin?range=30` (`today`, `7`, `30`, `90`, `custom&from=&to=`) | `GET /admin/dashboard/` |
| Analytics and reports (+ CSV export) | `/admin/reports` | `GET /admin/dashboard/`, `GET /admin/orders/export/` |
| Orders (filters, export CSV, status, cancel) | `/admin/orders`, `/admin/orders/:id` | `GET /admin/orders/`, `/admin/orders/:id/`, `POST …/status/`, `…/cancel/`, `GET /admin/orders/export/` |
| Products, import | `/admin/products…` | `/products/…` (existing) |
| Categories (read-only) | `/admin/categories` | `GET /admin/categories/` |
| Stores | `/admin/stores` | `/admin/stores/`, `…/status/` |
| Customers, customer profile | `/admin/customers`, `/admin/customers/:id` | `GET /admin/customers/`, `/admin/customers/:id/` |
| Delivery partners | `/admin/partners` | `/admin/delivery-partners/…` |
| Users and roles | `/admin/users` | `/admin/users/…` |
| Deliveries (assign, retry, cancel) | `/admin/deliveries…` | `/admin/deliveries/…` |
| Reviews, feedback, tickets, complaints | `/admin/reviews`, `/admin/feedback`, `/admin/support/…` | existing review, feedback and support APIs |
| Notifications, Audit log | `/admin/notifications`, `/admin/audit` | existing |
| Global search | top bar | `GET /admin/search/?q=` |
| Sidebar counts | sidebar | `GET /admin/counts/` |

### What the dashboard numbers mean
* **Right now** cards are live snapshots (not tied to the period): orders awaiting confirmation, orders being prepared (store order accepted/preparing), awaiting delivery (store order ready, or delivery waiting for a partner), in transit, deliveries needing attention, open tickets, unresolved complaints, partners online.
* **Period** cards use the chosen local-date range and the equally long range just before it. `change_percent` is `null` (shown as "No earlier data to compare") when the earlier period is 0; it is never shown as 0% or infinity.
* **Delivered order value** is the sum of `grand_total` of orders with status Delivered whose `delivered_at` is in the period. There is no payment gateway, refund record or coupon model in the backend, so Payments, Refunds and Promotions pages are **not** offered.
* Charts: orders per day, delivered value per day, cancellations per day, customer growth, deliveries completed, failed delivery attempts, order status, top stores (delivered store-order value), best-selling products (quantity, excluding cancelled or rejected lines), delivery performance (success rate and average assignment-to-delivery minutes, only when data exists).
* Ranges are limited to 366 days; invalid ranges return HTTP 400 with a field message.

## 3. Run it
```bash
cd backend && python manage.py migrate && python manage.py runserver 8000
cd frontend && npm install && npm run dev            # http://127.0.0.1:5173/admin
```
Sign in at `/login` with an Admin or Super Admin account (create one with `python manage.py createsuperuser`; the command assigns the Super Admin role).

## 4. Configuration
| Variable | Where | Meaning |
|---|---|---|
| `DJANGO_ADMIN_URL` | backend | Path of the Django fallback admin (default `django-admin/`). |
| `VITE_API_BASE_URL` | frontend build | API base (default `/api/v1`, same origin). |
| `VITE_DEV_BACKEND_URL` | frontend dev | Where the dev server proxies `/api`, `/media`, `/static`, `/django-admin`. |

The React app owns `/admin`; Django owns `/api`, `/media`, `/static`, `/django-admin` and `/health`. The proxy in front must route accordingly.

## 5. Roles and permissions
* Only `ADMIN` and `SUPER_ADMIN` reach `/admin`; everyone else sees "access denied", and the API refuses them regardless of what the UI shows.
* Order-related data (dashboard, customers, export, order search) additionally requires the `orders.view_order` permission for `ADMIN`; Super Admins have it implicitly. An Admin without it receives HTTP 403 on those endpoints.
* The project has no operations/product/finance/support-lead sub-roles. They were not invented; use Django Groups and permissions for finer control.

## 6. Add a dashboard metric
1. Add the aggregation to `DashboardView` in `backend/platform_api/analytics.py` (aggregate in the database; keep it a count or sum).
2. Add the field to `DashboardData` in `frontend/src/types/ops.ts`.
3. Render it with `KpiCard` or `TrendChart`/`BarList` in `pages/admin/AdminOverview.tsx` or `AdminReports.tsx`.
4. Add a test in `backend/platform_api/tests_analytics.py` that compares it with the ORM.

## 7. Add a management page
1. Endpoint in `platform_api` (+ route in `platform_api/urls.py`, permission class `IsManagement`, test for 403s).
2. Service call in `frontend/src/services/ops.ts`, types in `types/ops.ts`.
3. Page in `src/pages/admin/` using `DataTable`, `QueryBoundary`, `useUrlState` (filters live in the URL).
4. Route in `router.tsx`, entry in `ADMIN_NAV` (optionally a badge in `AdminLayout.tsx`'s `BADGES`).

## 8. Tests and checks
```bash
cd backend && python manage.py check && python manage.py makemigrations --check --dry-run
DJANGO_SECRET_KEY=x python manage.py test platform_api.tests_analytics deliveries.tests_admin --noinput
DJANGO_SECRET_KEY=x DATABASE_URL=postgresql://… python manage.py test --noinput --parallel 4    # full suite
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

## 9. Deployment
Build `frontend/dist`, serve it for every path except `/api`, `/media`, `/static`, `/django-admin`, `/health`; route those to Django (`collectstatic` first). Do not expose `/django-admin/` publicly if it is not needed.

## 10. Verification performed
* 12 new backend tests (dashboard numbers vs ORM, range handling and validation, previous-period behaviour, permission refusals, query count, customers, CSV export incl. spreadsheet-formula neutralising, search, categories).
* 8 new frontend tests (real numbers and filtered links, period switch refetches with a 7-day window, error state with retry, sidebar badges and collapse persistence, global search, charts empty and accessible states, customers empty state); all frontend tests pass.
* Headless Chromium against a throwaway SQLite database holding 41 orders: dashboard (4 period variants), reports, customers, customer profile, categories, orders at 1366, 768 and 390 px: no horizontal overflow, one `<h1>` per page, no unlabeled controls, no console errors, no failed requests.

## 11. Known limitations
* No payments, refunds, coupons, inventory-wide or delivery-zone pages: the backend has no such data or endpoints, so no menu entries exist for them.
* No "business settings" or integrations page: there is no settings model or endpoint.
* Categories are view-only (no category write API); Super Admins edit them in the Django fallback admin.
* Customers are managed (suspend/reactivate) through Users; there is no customer-edit endpoint.
* Bulk actions exist in the Django fallback admin, not in the React tables.
* Orders CSV export is capped at 20,000 rows.
* Not tested on real phones, Safari or Firefox; no screen-reader walkthrough. Large-data performance was not load-tested.

## 12. Stores, imports and approvals (added)
* **Stores** group: All stores, Add store (wizard with draft save and unsaved-change protection), Pending approvals. Store detail has tabs for overview, profile, address, hours, delivery, staff, documents, verification, products, orders and history.
* **Administration** group: Approval center (one place for every queue, with badge), Import products (column mapping, row fixing, retry), Bulk import jobs, Audit log.
* Bulk actions appear on Products and Stores for users with the matching rights; every bulk action previews first and needs confirmation.
* **Design system:** one `Button` (sizes `sm`/`md`/`lg`, variants primary/secondary/outline/ghost/destructive, icon-only needs `aria-label`) and `ButtonLink` for navigation. Links navigate, buttons act, tabs switch sections, menus hold row actions; no native `alert`/`confirm`.
* Full behaviour: see [admin-approval-and-import-workflows.md](admin-approval-and-import-workflows.md).

## 13. Pricing and owner onboarding (added)
* Product → edit shows **Price & profit** (for users with the pricing permission): store price, selling price or target margin (suggestion only), discount, live final price, profit, margin and markup. See [product-pricing-workflow.md](product-pricing-workflow.md).
* Products list → select rows → **Set margin** previews every product and blocks any that would sell below cost.
* Add store → **Owner** offers setup link, existing user, password or later. See [store-onboarding-guide.md](store-onboarding-guide.md). `/setup-account` is the page owners open from their link.
