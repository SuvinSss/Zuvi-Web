"""Checkout with server-side delivery quotes: price integrity, snapshots and idempotency."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from cart.models import CartItem
from orders.checkout import place_customer_order
from orders.models import FulfillmentType, Order, PaymentMethod

from . import quotes
from .models import DeliveryQuote, QuoteStatus
from .testing import make_pricing_config, route_ok
from .tests_quotes import QuoteTestBase


class CheckoutWithQuoteTests(QuoteTestBase):
    def place(self, token="tok-1", quote_id=None, **kw):
        return place_customer_order(
            customer=self.customer, checkout_token=token, fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD, delivery_address_id=self.address.pk, actor=self.user,
            delivery_quote_id=quote_id, **kw,
        )

    def quote(self, meters=4000):
        self.google.push(*route_ok(meters, 600))
        return quotes.create_quote(self.customer, self.address)

    def test_order_uses_the_server_quote_and_stores_an_immutable_snapshot(self):
        quote = self.quote()
        order = self.place(quote_id=quote.pk)
        subtotal = (self.product.final_price * 2).quantize(Decimal("0.01"))
        self.assertEqual(order.items_subtotal, subtotal)
        self.assertEqual(order.delivery_charge, Decimal("44.00"))
        self.assertEqual(order.discount_total, Decimal("0.00"))
        self.assertEqual(order.grand_total, subtotal + Decimal("44.00"))
        self.assertEqual(order.store_orders.get().delivery_charge, Decimal("44.00"))
        self.assertEqual(order.delivery_quote_id, quote.pk)
        self.assertEqual(order.delivery_pricing_snapshot["pricing_version"], 1)
        quote.refresh_from_db()
        self.assertEqual(quote.status, QuoteStatus.CONSUMED)

    def test_free_delivery_offer_keeps_charge_and_discount_separate(self):
        make_pricing_config(version=2, free_delivery_threshold=Decimal("100"))
        order = self.place(quote_id=self.quote().pk)
        self.assertEqual(order.delivery_charge, Decimal("44.00"))
        self.assertEqual(order.discount_total, Decimal("44.00"))
        self.assertEqual(order.grand_total, order.items_subtotal)

    def test_later_pricing_changes_do_not_rewrite_the_historical_charge(self):
        order = self.place(quote_id=self.quote().pk)
        make_pricing_config(version=2, customer_base_fee=Decimal("500"), customer_maximum_fee=Decimal("900"))
        order.refresh_from_db()
        self.assertEqual(order.delivery_charge, Decimal("44.00"))
        self.assertEqual(order.delivery_pricing_snapshot["delivery_fee"], "44.00")
        self.assertEqual(order.delivery_pricing_snapshot["pricing_version"], 1)

    def test_a_quote_cannot_be_used_twice(self):
        quote = self.quote()
        self.place(quote_id=quote.pk)
        add_again = self.product
        from cart.services import add_product_to_cart

        add_product_to_cart(customer=self.customer, product_code=add_again.product_code, quantity=Decimal("2"))
        with self.assertRaises(ValidationError) as ctx:
            self.place(token="tok-2", quote_id=quote.pk)
        self.assertIn("delivery_quote", ctx.exception.message_dict)
        self.assertEqual(Order.objects.count(), 1)

    def test_same_checkout_token_returns_the_same_order(self):
        quote = self.quote()
        first = self.place(quote_id=quote.pk)
        again = self.place(quote_id=quote.pk)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Order.objects.count(), 1)

    def test_changed_basket_is_refused_and_nothing_is_written(self):
        quote = self.quote()
        from cart.services import add_product_to_cart

        add_product_to_cart(customer=self.customer, product_code=self.product.product_code, quantity=Decimal("1"))
        with self.assertRaises(ValidationError):
            self.place(quote_id=quote.pk)
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(CartItem.objects.exists())
        quote.refresh_from_db()
        self.assertEqual(quote.status, QuoteStatus.ACTIVE)

    def test_not_enforced_without_a_quote_keeps_legacy_free_delivery(self):
        order = self.place()
        self.assertEqual(order.delivery_charge, Decimal("0.00"))
        self.assertIsNone(order.delivery_quote_id)
        self.assertEqual(order.delivery_pricing_snapshot, {})

    @override_settings(DELIVERY_QUOTES_ENFORCED=True)
    def test_enforced_mode_requires_a_quote(self):
        with self.assertRaises(ValidationError) as ctx:
            self.place()
        self.assertIn("delivery_quote", ctx.exception.message_dict)
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(DELIVERY_QUOTES_ENFORCED=True)
    def test_enforced_mode_accepts_a_valid_quote(self):
        self.assertEqual(self.place(quote_id=self.quote().pk).delivery_charge, Decimal("44.00"))

    def test_another_customers_quote_id_is_rejected(self):
        other, other_user = self.make_customer("thief")
        other_address = self.make_address(other)
        quote = self.quote()
        from cart.services import add_product_to_cart

        add_product_to_cart(customer=other, product_code=self.product.product_code, quantity=Decimal("2"))
        with self.assertRaises(ValidationError):
            place_customer_order(
                customer=other, checkout_token="thief-1", fulfillment_type=FulfillmentType.DELIVERY,
                payment_method=PaymentMethod.COD, delivery_address_id=other_address.pk, actor=other_user,
                delivery_quote_id=quote.pk,
            )
        self.assertEqual(DeliveryQuote.objects.get(pk=quote.pk).status, QuoteStatus.ACTIVE)
