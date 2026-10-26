# Location and address workflow

## Customer: choosing where to deliver

The header shows **Delivering to / Home · 12 Market Rd / Change location**. Opening it offers:

1. **Search**: Places autocomplete (India-biased), debounced, one session token per search.
2. **Use my current location**: handles permission denied, unavailable, timeout and unsupported devices with
   a clear message and the search fallback. If accuracy is worse than 100 m the user is told to drag the pin.
3. **Pin**: drag the marker or tap the map. Each move is reverse-geocoded through the backend. If Google can't
   match a street address the form says the pin is not fully verified and asks for a landmark.
4. **Saved addresses**: Home, Work and custom labels. A customer can only see, change or delete their own
   addresses; anything else returns 404.

Saving an address requires the customer to tick **The pin is at my exact delivery spot**
(`location_confirmed`). The address stores latitude and longitude (six decimals), the Google place ID, how the
location was chosen, and when it was confirmed.

A signed-out visitor can choose a location to browse stores near them. Address lookup for a pin and saved
addresses need a customer sign-in, because they cost money or hold personal data.

## Which stores deliver here

`GET /api/v1/stores/nearby/` is a free, approximate check: a store qualifies if its confirmed pin is within its
delivery radius (straight line). It is labelled approximate. The real road distance is only measured when a
quote is created at checkout.

A store can take delivery orders only when it is active, has a pin inside India that isn't (0,0), has
confirmed that pin, and doesn't share its exact location with another store. Reasons are reported to admins
with the action to fix each one.

## Stores: placing the pin

Store users open **Store location**, search or drag the pin to the pickup door, adjust the address, tick the
confirmation and save. Moving the pin clears the old confirmation unless re-confirmed. Only admins can change
the delivery radius.

## Delivery partners

Each assignment shows pickup and drop-off addresses with a **Navigate in Google Maps** link
(`travelmode=two-wheeler`), the quoted road distance and its `LIVE` or `CACHED` label, and one button for the
next step. Drop-off details only appear while the delivery is active. Partners see only their own assignments
and never see the customer's fee or their own payout calculation inputs.

## Not built

There is no live rider tracking: the app has no rider location feed. Order tracking shows status and map
points, and states that no delivery time is estimated.
