# Zuuvi web frontend

One React single-page app (`frontend/`) serves every role. It talks only to `/api/v1/` (see `docs/platform-api.md`).
Stack: React 19, TypeScript (strict), Vite, Tailwind 4 (tokens in `src/styles/index.css`), React Router 7, TanStack Query,
react-hook-form + zod (product form), axios. No UI framework and no map library.

## Run it
```bash
# backend (throwaway SQLite is fine locally)
cd backend && python manage.py migrate && python manage.py runserver      # http://127.0.0.1:8000
# frontend
cd frontend && npm install && npm run dev                                # http://127.0.0.1:5173 (proxies /api and /media)
npm run typecheck && npm run lint && npm test && npm run build
```
Production: serve `frontend/dist` and route `/api`, `/media` to Django. Do not deploy this branch to the live site until
that routing is in place.

## Areas and routes
| Area | Who | Routes |
|---|---|---|
| Public | everyone | `/`, `/shop`, `/shop/:code`, `/stores`, `/stores/:id`, `/help`, `/login`, `/register`, `/register-partner`, `/forgot-password`, `/reset-password` |
| Customer | `CUSTOMER` | `/cart`, `/checkout`, `/account`, `/account/orders[/:id]`, `/account/addresses`, `/account/reviews`, `/account/feedback`, `/account/notifications`, `/account/support[/new-ticket, /new-complaint, /tickets/:id, /complaints[/:id]]` |
| Store | `STORE_USER` | `/store`, `/store/orders[/:id]`, `/store/products[/new, /:id]`, `/store/stock`, `/store/deliveries`, `/store/reviews`, `/store/notifications` |
| Delivery partner | `DELIVERY_AGENT` | `/delivery`, `/delivery/assignments[/:id]`, `/delivery/profile`, `/delivery/notifications` (mobile bottom navigation) |
| Support | `SUPPORT_AGENT`, `SUPPORT_SUPERVISOR` | `/support`, `/support/tickets[/:id]`, `/support/complaints[/:id]`, `/support/feedback`, `/support/notifications` |
| Admin | `ADMIN`, `SUPER_ADMIN` | `/admin` (dashboard), `/admin/reports`, `/admin/customers[/:id]`, `/admin/categories`, `/admin/orders[/:id]`, `/admin/deliveries[/:id]`, `/admin/users`, `/admin/stores`, `/admin/partners`, `/admin/products[/new, /:id, /import]`, `/admin/reviews`, `/admin/support/tickets|complaints[/:id]`, `/admin/feedback`, `/admin/audit`, `/admin/notifications` |

Access is enforced by `RequireRole` (`src/routes/guards.tsx`) for navigation convenience only; the API enforces the real rules.
A signed-in user who opens another role's area sees an "access denied" page, not a redirect loop.

## Design rules used
* Status is always text plus a marker, never colour alone. Every form control has a visible label; errors are announced (`role="alert"`).
* Lists keep their filters in the URL (`useUrlState`), so refresh, sharing and the back button work. Tables become stacked cards on phones.
* Dialogs use the native `<dialog>` element (focus trap and Esc come from the browser). Touch targets are at least 44 px.
* Nothing sensitive is stored in the browser: the session is the HttpOnly cookie; CSRF token is kept in memory.
* No fabricated data: tracking shows the real last ping, its age and a stale warning; ETA is never shown because the API returns none.

## API → UI coverage
| API group | Screen(s) | Notes |
|---|---|---|
| auth: signin, session, logout, register, partner-register, password reset/change, me | Login, Register, Forgot/Reset, Account | `auth/login/` (management-only) and `auth/token*` are not used by the web app |
| public catalogue, store and product reviews | Home, Shop, Product, Stores, Store | |
| customer addresses, cart, checkout (preview + place, idempotent), orders, cancel | Addresses, Cart, Checkout, Orders, Order | |
| order tracking, delivery evidence photos | Order (customer) | pickup proof is never requested by customers |
| reviews (create/edit/withdraw/report) | Order, My reviews, product/store pages | |
| feedback (customer) | Feedback | staff list/reply/status/escalate in Support/Admin Feedback |
| support tickets & complaints, attachments, summary, agents | Support lists, forms, details, Support queue | attachments up to 3 files, 5 MB |
| notifications (list, unread count, read, read-all) | Notifications page + bell in every layout | notification preferences endpoint has **no screen yet** |
| store: me, orders + action, products CRUD, images (upload), stock, deliveries, confirm-pickup, reviews + reply, meta | Store area | |
| delivery partner: me, online, assignments, accept/reject, arrive-store, pickup, arrive, complete, fail, location, ratings, evidence | Delivery area | `tracking-history` has **no screen** |
| admin: overview, users suspend/reactivate, stores status, orders (list/detail/status/cancel), deliveries (list/detail/assign/retry/cancel/attempts), partners approve/reject/suspend, reviews moderation, audit, products + import | Admin area | |

## Backend gaps the UI cannot paper over
* **Addresses need coordinates** (`latitude`/`longitude` are required) and there is no geocoding endpoint. The address form offers
  "use my current location" or manual entry.
* **No ETA / routing provider.** The UI says estimates are unavailable. Navigation opens an external maps link.
* **Store users cannot delete a product photo or change the primary one**, and cannot use the Excel import (both are admin-only endpoints).
* **No store profile / opening-hours / settings endpoint.** The store area cannot edit them.
* **Admin cannot list customers separately**; use Users. No endpoint to edit another user's profile.
* **Feedback has no attachments or rating** in the API.
* **No notification-preferences screen** and **no GPS-trail screen** (endpoints exist).
* **Live location sharing only runs while the partner's screen is open** (a web page cannot track in the background).

## Verification (what was actually run)
* `npm run typecheck`, `npm run lint`, `npm test` (6 files, 39 tests), `npm run build`: all passed.
* Backend: `platform_api` tests pass (new store-meta test); the earlier full PostgreSQL run (717 tests) predates this frontend work.
* **Browser pass** (headless Chromium via Playwright against a throwaway SQLite backend seeded from the test fixtures): 52 screens across
  the public, customer, store, delivery-partner and admin areas, each loaded at 320×568, 360×640, 375×667, 390×844, 414×896, 768×1024,
  1024×768, 1280×720, 1440×900 and 1920×1080 (520 page loads). Automated checks per load: horizontal overflow, a single `<h1>`,
  unlabeled form controls, uncaught page errors / console errors / HTTP 5xx.
  Result of the final pass: **0** overflow, **0** unlabeled controls, **0** page or console errors, **0** server errors.
  The first pass found and I fixed: filter rows squeezing the search box (overflow at 375–414 px), a duplicate search-box id, and
  small text links.
* **Not tested:** the support-agent area (no support user in the seed; same components are used under `/admin/support`), real
  camera capture, real GPS/background location, screen-reader walkthroughs, keyboard-only walkthrough of every flow, Safari/Firefox,
  real devices. The check does not exercise submit flows (checkout, delivery completion); those are covered by backend tests and by
  component tests only partly.
* Remaining known issue: about a dozen in-sentence or footer text links are shorter than 32 px (my own, stricter-than-WCAG threshold).
