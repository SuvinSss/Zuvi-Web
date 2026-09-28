# ZuuVi UI/UX audit — 28 September 2026

## Scope and environment

Reviewed the Django templates, public catalogue presentation, cart JavaScript, location selection, customer authentication/account pages, checkout, store portal and management portal. Applied the frontend-skill. Kept the existing Django/Bootstrap stack and backend services.

Browser review used a separate local PostgreSQL database, `zuvi_ui_review_20260928`, with 13 sample products and dedicated customer, store and super-admin accounts. Stock was created through the inventory service. Existing `zuvi_dev` catalogue data was not modified. The isolated preview runs on localhost:8001. Temporary settings and credentials are outside the repository. No deployment was performed.

## Reference research

- [Amazon's official shopping guide](https://www.aboutamazon.in/news/retail/9-tips-to-get-started-on-amazon): search, explicit filters, cart review and address selection. Amazon.in listing requests returned HTTP 503, so this is a documented-flow reference, not a live visual inspection of its current listing UI.
- [Zomato delivery catalogue](https://www.zomato.com/ncr/delivery?user_lang_change=1): location/search orientation, category discovery and scannable listings.
- [Swiggy restaurant page](https://www.swiggy.com/restaurants): location context and prominent search, sign-in and cart entry points. The fetched page exposed only a limited shell; no authenticated order flow was inspected.

These informed interaction choices, not copied branding or unsupported claims. No artificial ratings, countdowns, delivery-time promises, payment options or live tracking were added.

## Design direction

Visual thesis: a calm neighbourhood shop with forest-green actions, warm neutral surfaces, clear typography and generous separation between tasks.

Content plan: shopping introduction, category discovery, featured products, newest products, and a factual COD reminder. Account, store and management surfaces use task-oriented labels.

Interaction thesis: preserve the sticky search header; use restrained category/product hover feedback; retain accessible Bootstrap menus and drawers with reduced-motion support. Cart changes provide an announced success/error response.

## Findings and implementation

| Finding | Change |
| --- | --- |
| Customer pages switched from a light storefront to a separate dark navigation with repeated cart entries. | Customer account, cart and checkout now inherit the public shell; account sections have a dedicated navigation strip. |
| Promotional cards and tiny category icons competed with shopping. | Simplified introduction and category discovery; consistent product grids, readable category icons and explicit browse actions. |
| Product add buttons lacked item-specific accessible names. | Each add action names its product; missing images have an explicit placeholder. Real product images retain alt text and lazy loading. |
| Product gallery thumbnails were static images. | Thumbnails are keyboard-operable buttons with selected state and update the main image. |
| Invalid maximum-price errors were not rendered and the filter panel stayed collapsed. | Filter errors render alongside fields, with the error panel expanded and accessible labels for search/sort. |
| Cart table required lateral navigation on phones. | Replaced it with responsive item rows and one clear checkout summary. Existing endpoints, quantities, prices and warning data are unchanged. |
| Cart network failure blindly retried an add POST as a normal submission. | An uncertain result now advises checking the cart before retrying, avoiding an automatic duplicate mutation. |
| Cart feedback was visual-only; cart bar also appeared during checkout. | Announced feedback and busy state; checkout no longer competes with the floating cart bar. |
| Checkout exposed “server”, “MVP” and deferred radius implementation details. | Plain customer copy, COD explanation and clearer address selection. The established delivery-eligibility notice remains. |
| Location picker automatically interrupted each catalogue visit. | Browsing stays open; the header still opens the same picker and checkout still requires an eligible owned address. |
| Sign-in had two level-one headings and an unchanging password-toggle label. | One page heading, autocomplete hints, linked field errors and a Show/Hide password label that follows the current state. |
| Customer dashboard advertised a nonfunctional tracking action. | Replaced it with the existing saved-address journey. |
| Store/admin pages lacked consistent branding, active navigation and filter labels. | Shared ZuuVi styling, active-page indication, labeled core list filters, clearer table hierarchy and keyboard-focusable overflowing tables. |
| Management links repeated “Open Module”. | Links name the module they open. |
| Error messages could use an unsupported Bootstrap `alert-error` class. | Shared shells map error messages to the danger style and announce them. |

## Preserved constraints

No database schema, authentication backend, permissions, pricing calculation, checkout service, stock service or order-state service was changed. CSRF-protected POSTs, queryset isolation and existing template permission gates remain. Store-portal navigation is additionally limited to the store role. Public product cards continue hiding merchant identity and internal pricing, as required by existing regression coverage. No payment gateway or delivery-agent feature was introduced.

## Browser verification

Desktop: 1440 × 1000. Primary mobile: 390 × 844. The homepage was additionally checked at widths 320 and 768; the document width matched the viewport at all four tested widths.

| Journey / state | Result |
| --- | --- |
| Homepage, categories, product list | Rendered on desktop/mobile; no document-level horizontal overflow on tested homepage widths. |
| Empty search and invalid price range | Recovery action visible; maximum-price error shown in expanded filters. |
| Customer login required fields | Both field errors displayed; password toggle changes accessible name; valid fixture login succeeds. |
| Keyboard entry | Tab reaches the skip link with a visible outline. |
| Cart add and quantity increment | Success announced; quantity and server subtotal updated. |
| Mobile cart | Item controls and summary fit within 390px without document overflow. |
| COD checkout | Only COD present; no floating cart bar; fixture order placed successfully with payment pending. |
| Cancellation | Order history preserved. Product balance restored to 10.000; inventory history contains opening movement, reservation and restoration. Cancelled order payment state follows the existing service. |
| Product gallery | Second thumbnail updates image URL and `aria-pressed`. |
| Store portal | Dashboard rendered on desktop/mobile; product search returns empty state. |
| Management portal | Dashboard rendered on desktop/mobile; product search narrowed to tomatoes; required product fields remained enforced. |
| Operational table | Mobile document stays within 390px; overflowing table exposes a keyboard-focusable region. |
| Browser errors | No console errors observed in the final customer verification tab. |

## Automated verification

- `manage.py check`: passes.
- `node --check`: passes for shared UI, cart and location-gate scripts.
- `git diff --check`: passes.
- Initial full PostgreSQL run: 822 tests, two failures exposing established presentation requirements (merchant privacy and delivery notice). Both were corrected without weakening those tests.
- Focused rerun: 54 tests passed.
- Final full-suite result: **822 tests passed in 180.562 seconds**, recorded in `artifacts/ui-ux/verification.txt`.

## Limits and follow-up

- The original local catalogue was empty. Screenshots use isolated sample data; product photography was unavailable. Two solid-color test images were added only for gallery verification. Real approved product photos remain the largest visual-content improvement.
- Maps search/GPS and geocoding were not end-to-end tested with a live Google Maps key. Saved-address selection was verified. Browser error handling does not substitute for checking Maps credentials and quotas.
- This is browser and code-based accessibility verification, not a formal WCAG certification or a full screen-reader audit. No real-device Safari/Android or production performance test was performed.
- Some operational tables remain wide because they expose detailed records. They scroll within labeled regions on phones; dedicated compact record views would be a separate larger design change.
- Some existing management/store dashboard cards and planned-module placeholders remain. Changes focus on existing workflows and do not implement postponed features.
- Screenshot fixture contents vary where interaction tests changed a cart or created/cancelled an order. Comparisons show the layout changes rather than a pixel-diff assertion.

## Screenshots

Open [the comparison gallery](../artifacts/ui-ux/comparison.html) for desktop and mobile images, including before/after storefront, cart, checkout, account and portals.
