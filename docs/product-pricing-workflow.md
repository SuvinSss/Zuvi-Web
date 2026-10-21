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

## Approval and publication
Statuses: Draft → Pending → Approved → Inactive / Rejected (existing transition table in `catalog/status.py`). Approval needs a complete price and image; approval and the `is_active` flag stay separate; pending and rejected products are never purchasable. Imports never approve. Bulk approval previews eligible/blocked records and rechecks each record.

## Not implemented (assumptions and gaps)
* **Scheduled or time-limited offers**, "special offer price" type, quantity or minimum-purchase conditions, store-wide offers and coupons: the system has no such models. Discounts are permanent until changed. Adding them touches catalogue, cart and checkout and was left out rather than half-built.
* **Tax (GST), payment fees, commission and shipping** are not part of product profit.
* **Store-owner price proposals** and a "Needs Information" product status do not exist; use Reject with a reason.
* Customers see the final price; the UI does not show a crossed-out reference price.
