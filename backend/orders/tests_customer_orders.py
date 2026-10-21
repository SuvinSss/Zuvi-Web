"""
Customer order history / detail / cancel pages and cross-customer isolation.
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user

from .checkout import place_customer_order
from .models import FulfillmentType, Order, OrderStatus, PaymentMethod
from .tests_checkout import CheckoutTestMixin

User = get_user_model()


class CustomerOrderPortalTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "order-alice",
                "email": "order-alice@example.com",
                "first_name": "Alice",
                "last_name": "Orders",
                "phone_number": "9000000801",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "order-bob",
                "email": "order-bob@example.com",
                "first_name": "Bob",
                "last_name": "Orders",
                "phone_number": "9000000802",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.store = self.create_store(name="Portal Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Portal Milk",
            stock=Decimal("20.000"),
            store_price=Decimal("80.00"),
            profit_margin=Decimal("20.00"),
        )
        self.pickup = self.create_pickup(self.store)
        self.address_a = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Orders",
                "phone_number": "9000000801",
                "line1": "11 Alice Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "Gate code 11",
                "is_default": True,
            },
        )
        self.address_b = create_customer_delivery_address(
            customer=self.customer_b,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Bob Orders",
                "phone_number": "9000000802",
                "line1": "22 Bob Secret Road",
                "line2": "",
                "landmark": "",
                "city": "Mysuru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "570001",
                # Within delivery range of the test store (delivery is priced and range-checked at checkout).
                "latitude": "12.935800",
                "longitude": "77.624400",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self.client = Client(enforce_csrf_checks=True)


    def _place_for(self, customer, user, *, token, quantity=Decimal("2.000"), **kwargs):
        add_product_to_cart(
            customer=customer,
            product_code=self.product.product_code,
            quantity=quantity,
        )
        defaults = {
            "customer": customer,
            "checkout_token": token,
            "fulfillment_type": FulfillmentType.DELIVERY,
            "payment_method": PaymentMethod.COD,
            "delivery_address_id": (
                self.address_a.pk
                if customer.pk == self.customer_a.pk
                else self.address_b.pk
            ),
            "actor": user,
        }
        defaults.update(kwargs)
        return place_customer_order(**defaults)














    def test_list_ignores_foreign_order_in_queryset(self):
        """Direct queryset helper never returns another customer's rows."""
        from .portal import customer_orders_queryset, get_customer_order_or_404

        order_a = self._place_for(
            self.customer_a, self.user_a, token="tok-qs-a"
        )
        order_b = self._place_for(
            self.customer_b, self.user_b, token="tok-qs-b"
        )
        own = list(customer_orders_queryset(self.customer_a))
        self.assertEqual([o.pk for o in own], [order_a.pk])
        self.assertNotIn(order_b.pk, [o.pk for o in own])
        found = get_customer_order_or_404(
            self.customer_a, order_a.order_number
        )
        self.assertEqual(found.pk, order_a.pk)
        from django.http import Http404

        with self.assertRaises(Http404):
            get_customer_order_or_404(self.customer_a, order_b.order_number)
