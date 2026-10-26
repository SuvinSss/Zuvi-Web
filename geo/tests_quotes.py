from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from cart.services import add_product_to_cart
from orders.tests_checkout import CheckoutTestMixin

from . import quotes
from .errors import MapsNetworkError, PricingNotConfigured, QuoteError
from .models import DeliveryQuote, QuoteStatus
from .testing import DeliveryFixtureMixin, GoogleFakeMixin, make_pricing_config, matrix_ok, route_ok


class QuoteTestBase(GoogleFakeMixin, DeliveryFixtureMixin, CheckoutTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.customer, self.user = self.make_customer()
        self.address = self.make_address(self.customer)
        self.store = self.confirm_store(self.create_store(name="Quote Store"))
        self.product = self.create_public_product(store=self.store, name="Quote Milk", stock=Decimal("20"))
        add_product_to_cart(customer=self.customer, product_code=self.product.product_code, quantity=Decimal("2"))
        self.config = make_pricing_config()

    def second_store(self, lat="8.820000", lng="76.680000"):
        store = self.confirm_store(self.create_store(name="Second Store"), lat, lng)
        product = self.create_public_product(store=store, name="Second Rice", stock=Decimal("20"))
        add_product_to_cart(customer=self.customer, product_code=product.product_code, quantity=Decimal("1"))
        return store


class CreateQuoteTests(QuoteTestBase):
    def test_creates_server_priced_quote_with_a_leg_per_store(self):
        self.google.push(*route_ok(4000, 600))
        quote = quotes.create_quote(self.customer, self.address)
        leg = quote.legs.get()
        self.assertEqual(quote.status, QuoteStatus.ACTIVE)
        self.assertEqual(quote.pricing_config_id, self.config.pk)
        self.assertEqual(leg.route_distance_meters, 4000)
        self.assertEqual(leg.route_source, "LIVE")
        self.assertEqual(leg.route_provider, "google_routes_v2")
        self.assertEqual(leg.fee_after_discount, Decimal("44.00"))
        self.assertEqual(leg.operational_cost, Decimal("43.00"))
        self.assertEqual(leg.rider_payout, Decimal("18.00"))
        self.assertEqual(quote.delivery_fee, Decimal("44.00"))
        self.assertEqual(leg.items_subtotal, (self.product.final_price * 2).quantize(Decimal("0.01")))
        self.assertGreater(quote.expires_at, timezone.now())
        self.assertEqual(len(quote.fingerprint), 64)

    def test_new_quote_supersedes_the_previous_active_one(self):
        self.google.push(*route_ok(4000, 600))
        first = quotes.create_quote(self.customer, self.address)
        second = quotes.create_quote(self.customer, self.address)  # route is cached
        first.refresh_from_db()
        self.assertEqual(first.status, QuoteStatus.SUPERSEDED)
        self.assertEqual(second.status, QuoteStatus.ACTIVE)
        self.assertEqual(second.legs.get().route_source, "CACHED")

    def test_two_stores_use_one_matrix_request_and_sum_the_fees(self):
        self.second_store()
        self.google.push(*matrix_ok([(0, 0, 4000, 600), (1, 0, 2000, 300)]))
        quote = quotes.create_quote(self.customer, self.address)
        self.assertEqual(quote.legs.count(), 2)
        self.assertEqual(len(self.google.calls), 1)
        self.assertEqual(quote.delivery_fee, sum(leg.fee_after_discount for leg in quote.legs.all()))

    def test_free_delivery_discount_is_recorded(self):
        make_pricing_config(version=2, free_delivery_threshold=Decimal("100"))
        self.google.push(*route_ok(4000, 600))
        quote = quotes.create_quote(self.customer, self.address)
        self.assertEqual(quote.delivery_fee, Decimal("0.00"))
        self.assertEqual(quote.delivery_discount, Decimal("44.00"))
        self.assertEqual(quote.delivery_fee_before_discount, Decimal("44.00"))

    def test_straight_line_prefilter_blocks_far_addresses_without_calling_google(self):
        far = self.make_address(self.customer, lat="9.500000", lng="77.500000")
        with self.assertRaises(quotes.NotServiceable) as ctx:
            quotes.create_quote(self.customer, far)
        self.assertEqual(ctx.exception.reasons[0]["code"], "OUTSIDE_RADIUS")
        self.assertEqual(self.google.calls, [])
        self.assertFalse(DeliveryQuote.objects.exists())

    def test_road_distance_over_the_limit_is_not_serviceable(self):
        self.google.push(*route_ok(20000, 2400))
        with self.assertRaises(quotes.NotServiceable) as ctx:
            quotes.create_quote(self.customer, self.address)
        self.assertEqual(ctx.exception.reasons[0]["code"], "OUTSIDE_ROAD_RANGE")

    def test_straight_line_is_not_road_distance(self):
        # About 3.7 km apart in a straight line but the road is 9 km: priced on 9 km.
        self.google.push(*route_ok(9000, 1200))
        quote = quotes.create_quote(self.customer, self.address)
        self.assertEqual(quote.legs.get().route_distance_meters, 9000)

    def test_no_route_is_reported_per_store(self):
        self.google.push(200, {})
        with self.assertRaises(quotes.NotServiceable) as ctx:
            quotes.create_quote(self.customer, self.address)
        self.assertEqual(ctx.exception.reasons[0]["code"], "NO_ROUTE")

    def test_transient_failure_is_reported_as_unavailable_not_as_too_far(self):
        self.google.push(0, raises=MapsNetworkError("down"))
        with self.assertRaises(MapsNetworkError):
            quotes.create_quote(self.customer, self.address)
        self.assertFalse(DeliveryQuote.objects.exists())

    def test_inactive_unapproved_or_pinless_stores_are_rejected(self):
        for change, code in (({"is_active": False}, "STORE_INACTIVE"), ({"status": "SUSPENDED"}, "STORE_NOT_APPROVED")):
            for field, value in change.items():
                setattr(self.store, field, value)
            self.store.save()
            with self.assertRaises(quotes.NotServiceable) as ctx:
                quotes.create_quote(self.customer, self.address)
            self.assertIn(code, [r["code"] for r in ctx.exception.reasons])
            self.store.is_active, self.store.status = True, "ACTIVE"
            self.store.save()
        self.store.address.latitude = self.store.address.longitude = Decimal("0")
        self.store.address.save()
        with self.assertRaises(quotes.NotServiceable) as ctx:
            quotes.create_quote(self.customer, self.address)
        self.assertEqual(ctx.exception.reasons[0]["code"], "STORE_LOCATION_MISSING")

    @override_settings(DELIVERY_QUOTES_ENFORCED=True)
    def test_unconfirmed_store_location_blocks_orders_when_enforced(self):
        self.store.location_confirmed_at = None
        self.store.save()
        with self.assertRaises(quotes.NotServiceable) as ctx:
            quotes.create_quote(self.customer, self.address)
        self.assertEqual(ctx.exception.reasons[0]["code"], "STORE_LOCATION_UNCONFIRMED")

    def test_unconfirmed_store_location_is_tolerated_while_not_enforced(self):
        self.store.location_confirmed_at = None
        self.store.save()
        self.google.push(*route_ok(4000, 600))
        self.assertEqual(quotes.create_quote(self.customer, self.address).status, QuoteStatus.ACTIVE)

    def test_missing_pricing_configuration(self):
        self.config.is_active = False
        self.config.save()
        with self.assertRaises(PricingNotConfigured):
            quotes.create_quote(self.customer, self.address)

    def test_empty_basket(self):
        from cart.models import CartItem

        CartItem.objects.all().delete()
        with self.assertRaises(QuoteError):
            quotes.create_quote(self.customer, self.address)


class LockValidQuoteTests(QuoteTestBase):
    def make_quote(self):
        self.google.push(*route_ok(4000, 600))
        return quotes.create_quote(self.customer, self.address)

    def test_a_fresh_quote_validates(self):
        quote = self.make_quote()
        self.assertEqual(quotes.lock_valid_quote(self.customer, quote.pk, self.address).pk, quote.pk)

    def test_another_customers_quote_is_indistinguishable_from_missing(self):
        quote = self.make_quote()
        other, _ = self.make_customer("someone-else")
        other_address = self.make_address(other)
        with self.assertRaises(QuoteError) as foreign:
            quotes.lock_valid_quote(other, quote.pk, other_address)
        with self.assertRaises(QuoteError) as missing:
            quotes.lock_valid_quote(other, quote.pk + 999, other_address)
        self.assertEqual(foreign.exception.public_message, missing.exception.public_message)

    def test_expired_quote(self):
        quote = self.make_quote()
        DeliveryQuote.objects.filter(pk=quote.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(QuoteError):
            quotes.lock_valid_quote(self.customer, quote.pk, self.address)

    def test_consumed_or_superseded_quote(self):
        quote = self.make_quote()
        for state in (QuoteStatus.CONSUMED, QuoteStatus.SUPERSEDED):
            DeliveryQuote.objects.filter(pk=quote.pk).update(status=state)
            with self.assertRaises(QuoteError):
                quotes.lock_valid_quote(self.customer, quote.pk, self.address)

    def test_basket_change_invalidates(self):
        quote = self.make_quote()
        add_product_to_cart(customer=self.customer, product_code=self.product.product_code, quantity=Decimal("1"))
        with self.assertRaises(QuoteError):
            quotes.lock_valid_quote(self.customer, quote.pk, self.address)

    def test_added_store_invalidates(self):
        quote = self.make_quote()
        self.second_store()
        with self.assertRaises(QuoteError):
            quotes.lock_valid_quote(self.customer, quote.pk, self.address)

    def test_address_change_invalidates(self):
        quote = self.make_quote()
        other = self.make_address(self.customer, lat="8.831000", lng="76.701000", is_default=False)
        with self.assertRaises(QuoteError):
            quotes.lock_valid_quote(self.customer, quote.pk, other)

    def test_new_pricing_version_invalidates(self):
        quote = self.make_quote()
        make_pricing_config(version=2)
        with self.assertRaises(QuoteError):
            quotes.lock_valid_quote(self.customer, quote.pk, self.address)

    def test_garbage_ids(self):
        for value in (None, "", "abc", "1; drop table"):
            with self.assertRaises(QuoteError):
                quotes.lock_valid_quote(self.customer, value, self.address)

    def test_snapshot_records_pricing_version_and_internal_costs(self):
        quote = self.make_quote()
        snapshot = quotes.build_order_snapshot(quote)
        self.assertEqual(snapshot["pricing_version"], 1)
        self.assertEqual(snapshot["legs"][0]["route"]["distance_meters"], 4000)
        self.assertEqual(snapshot["legs"][0]["rider_payout"], "18.00")
