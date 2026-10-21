# Product pricing and approval workflow

## Pricing model (what the code already did, now explained and editable)
Zuuvi buys from stores and sells to customers, so the catalogue carries one chain of prices:

| Concept | Field | Meaning |
|---|---|---|
| Store price (cost) | `store_price` | What Zuuvi pays the store per unit. Entered on the product or in an import. |
| Margin | `profit_margin_type` + `profit_margin` | Added by management: a fixed ₹ amount or a % of the store price. |
| Selling price | `selling_price` | Regular price before discount. Always calculated on the server. |
| Discount | `discount_type` + `discount_value` | Percentage or fixed ₹ off the selling price. |
| Final price | `final_price` | What the customer pays. Checkout copies it onto the order line (`unit_price`), so later repricing never changes past orders. |

Pricing is **platform-controlled**: store users cannot see or set margin, selling or final price; only management with `catalog.manage_product_pricing` (Super Admin implicit) can. Selling and final prices submitted by any client are ignored and re-derived.

## Terms and formulas
* **Estimated gross profit per unit** = final price − store price. It is *gross*: tax, payment fees and commission are not modelled in the catalogue, so the UI and API label it "Estimated gross profit (before tax, fees and commission)".
* **Profit margin** = profit ÷ final price × 100.
* **Markup** = profit ÷ store price × 100.
* Zero store price or zero final price returns no percentage (`null`), never an error or a made-up number.
* **Target margin → suggested price** = store price ÷ (1 − margin). Margin must be ≥ 0 and < 100. It is a suggestion only; nothing is saved until the person chooses "Use this price" and saves.

Worked example: store price ₹600, selling price ₹800, ₹100 discount → final ₹700, profit ₹100, margin 14.29%, markup 16.67%. This is covered by a test.

## Rules enforced on the server
* Selling price cannot be below the store price (it is stored as an exact fixed margin).
* Final price (after discount) cannot be below the store price unless `PRICING_ALLOW_BELOW_COST = True` in settings (default False).
* Percentage margin/discount ≤ 100; fixed discount < selling price; final price > 0.
* Every change writes price history and an audit entry.
* Customer-facing APIs never expose store price, margin or profit.

## API
* `POST /api/v1/products/pricing/preview/` – calculator; saves nothing. Body: `product` or `cost`, and `selling_price` or `margin_type`+`margin`, optional discount, optional `target_margin`.
* `POST /api/v1/products/<id>/pricing/` – set `selling_price` (or margin) and discount; optional `reason`.
* `POST /api/v1/admin/bulk/products/{preview,apply}/` with `action: "set_pricing"` and `params: {margin_type, margin}`; products where the margin is invalid or would sell below cost are blocked individually.
* Product detail includes a management-only `pricing` breakdown.

## Scheduled offers
* A discount can have an optional start and end time (`discount_starts_at`, `discount_ends_at`). Outside the window the customer pays the selling price; only one discount applies per product and it is never stacked.
* Checkout recalculates the price for every line, refreshes a stale stored price before charging, and copies the result onto the order line, so past orders keep their price.
* Cart, product cards and the public API read the current price (`Product.current_final_price`), so they are right even before the stored price is refreshed.
* Listing filters and sorting use the stored price. Run `python manage.py refresh_offer_prices` every few minutes (cron) to keep it current; automatic changes are written to price history with an empty "changed by".
* An offer cannot end before it starts or end in the past; it cannot push the price below the store price.

## Creating a product (React Admin → Products → Add product)
Five steps: **Product** (name, store, category, photo, description, pack size; SKU generated from the name unless you type one, brand under "More details"), **Stock** (stock on hand recorded as opening stock in the same transaction, low-stock level, dates), **Price** (store price, selling price or target-margin suggestion, live profit/margin/markup), **Offer** (optional discount and dates), **Review** (summary, what blocks approval). Finishing actions: *Save draft*, *Submit for approval*, and *Save and approve* (only with the approve permission and when photo, price and details are complete). Stock and price inputs only appear for people with those permissions. If a step after creation fails (e.g. the price is refused), the product is kept as a draft, never duplicated, and the page links to it.

## Approval and publication
Statuses and transitions (`catalog/status.py`):

| From | To |
|---|---|
| Draft | Pending |
| Pending | Approved, Rejected, **Needs information** |
| Needs information | Pending (store resubmits), Draft, Rejected |
| Rejected | Pending, Draft |
| Approved | Inactive, Pending |
| Inactive | Approved (reactivate), Pending |

* Rejected and Needs information require a note, which the store sees on the product.
* Store owners resubmit with **Submit for approval** (`POST /api/v1/store/products/<id>/submit/`).
* Management uses the buttons on the product page (`POST /api/v1/products/<id>/status/`), bulk actions or the Approval Center. Only transitions allowed from the current status and permitted for the person are shown, and the server checks again.
* Approval needs an active store, category, complete price, image and core details. Only Approved + active products are public or purchasable.
* Store owners never receive Zuuvi's margin or profit: the store product API omits `profit_margin`, `profit_margin_type` and `pricing`.

## Not implemented
* Tax (GST), payment fees, commission and shipping are not part of product profit: the system holds no tax rates and inventing them would be wrong.
* Coupons, store-wide or platform-wide offers, quantity or minimum-purchase conditions: no such models exist.
* Store owners propose the store price (their cost) but not the selling price; Zuuvi sets selling prices.
