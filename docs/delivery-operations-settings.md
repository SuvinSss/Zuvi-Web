# Delivery operations settings (React Admin → Delivery operations → Delivery pricing)

Every field is on one page in plain language, grouped as: Fuel and vehicle, Rider pay, Operations, Customer delivery fee, Offers, Surcharges and tax, Status. A Simulator tab and a History tab sit beside it.

## Versions, effective dates and audit
- Settings are never edited in place. Saving creates a new **version** with a required reason and an optional future "takes effect" time. The active version is the newest one whose time has passed.
- Each save writes an audit event `delivery_pricing.version_created` with the previous and new value of every changed field.
- Zones (below) can have their own versions; addresses outside any zone use the default.
- Orders already placed keep their own frozen breakdown.
- Permissions: `logistics.view_delivery_operations` (view settings, simulator, reports), `logistics.manage_delivery_pricing` (save versions, edit zones), `logistics.manage_partner_payouts` (mark rider earnings paid). Super Admins have all three.

## Initial values (illustrative, not verified)
The migration seeds version 1, marked **"Example numbers"**: petrol ₹115/litre (listings for 21 Oct 2026 showed about ₹113.74 statewide and ₹115.09 in Wayanad: planning reference only, not a live price), 40 km/litre, ₹1.50/km maintenance, rider ₹25 per order, ₹15 per failed attempt, factor 1.6, overhead ₹8, failure allowance 10%, base ₹25 including 2 km, ₹6 per extra km, min ₹20, max ₹79, nearest-rupee rounding, max 15 km, no free delivery, no tax.

Replace these with verified costs before relying on reports, then untick "These are example numbers". The page shows when the fuel price was last verified and warns after 7 days; the price is never fetched automatically, because no authorised live source is configured.

## Zones and serviceability
- **Zones** (Delivery operations → Zones): drawn by tapping corners on the map. Optional hard-to-reach surcharge. Stores can use a zone as their delivery area instead of a radius (store field `service_mode` = ZONE).
- A store is deliverable to an address only if: it is ACTIVE and active, offers delivery, accepts orders and ordering is enabled, it is open now (configured hours/closures; stores without hours count as open), it has a valid map pin, and the address is inside its radius (straight-line pre-check) or zone. Checkout then prices by road distance.
- Stores with missing or wrong pins are listed on Delivery operations and shown to the store owner with the fix.

## Routing fallback
With no road router configured, or when it fails, distance = straight line × `road_fallback_factor` (default 1.35) and is labelled **estimated** everywhere (customer, rider, reports). Untick "Allow orders when the road distance is only estimated" to refuse such deliveries instead.

## Tax
`delivery_tax_rate` stays 0 until the business's accountant confirms the GST treatment of delivery; tick "Tax treatment confirmed" when set.

## Cron jobs
- `python manage.py refresh_offer_prices` (product offers; unrelated to delivery but on the same scheduler)
- `python manage.py process_deliveries` (offer expiry, as before)
