"""
Customer order history / detail / cancel pages and cross-customer isolation.
"""

from decimal import Decimal

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
                "latitude": "12.295800",
                "longitude": "76.639400",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self.list_url = reverse("orders:customer_order_list")
        self.client = Client(enforce_csrf_checks=True)

    def _login(self, user):
        self.client.force_login(user)
        # Seed CSRF cookie via a GET.
        self.client.get(reverse("customers:customer_portal_dashboard"))

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

    def _detail_url(self, order_number):
        return reverse(
            "orders:customer_order_detail",
            kwargs={"order_number": order_number},
        )

    def _cancel_url(self, order_number):
        return reverse(
            "orders:customer_order_cancel",
            kwargs={"order_number": order_number},
        )

    def test_anonymous_redirected_to_login(self):
        login_client = Client()
        for url in (self.list_url, self._detail_url("ORD-MISSING")):
            response = login_client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/customer/login/", response.url)
        # Cancel is POST-only; unauthenticated POST still redirects to login
        # when CSRF is not enforced (auth gate runs after method check).
        response = login_client.post(
            self._cancel_url("ORD-MISSING"),
            {"reason": "Nope"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/customer/login/", response.url)

    def test_list_shows_only_own_orders(self):
        order_a = self._place_for(
            self.customer_a, self.user_a, token="tok-list-a"
        )
        order_b = self._place_for(
            self.customer_b, self.user_b, token="tok-list-b"
        )
        self._login(self.user_a)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order_a.order_number)
        self.assertNotContains(response, order_b.order_number)
        self.assertContains(response, "Delivery")
        self.assertContains(response, "Cash on Delivery")
        self.assertContains(response, "Placed")
        # List columns include totals and item count.
        self.assertContains(response, f"₹{order_a.grand_total}")
        orders = list(response.context["orders"])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].item_count, Decimal("2.000"))

    def test_detail_shows_snapshots_and_hides_internal_pricing(self):
        order = self._place_for(
            self.customer_a, self.user_a, token="tok-detail-a"
        )
        self._login(self.user_a)
        response = self.client.get(self._detail_url(order.order_number))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)
        self.assertContains(response, "Portal Milk")
        self.assertContains(response, "11 Alice Lane")
        self.assertContains(response, "Gate code 11")
        self.assertContains(response, "Status history")
        self.assertContains(response, "Payment")
        # Public unit price / line totals only — never store_price / margins.
        self.assertContains(response, f"₹{self.product.final_price}")
        self.assertNotContains(response, "store_price")
        self.assertNotContains(response, "profit_margin")
        self.assertNotContains(response, str(self.product.store_price))
        self.assertNotContains(response, "stock_restored")

    def test_detail_shows_pickup_location_for_pickup_orders(self):
        order = self._place_for(
            self.customer_a,
            self.user_a,
            token="tok-pickup-detail",
            fulfillment_type=FulfillmentType.FACILITY_PICKUP,
            payment_method=PaymentMethod.PAY_AT_PICKUP,
            delivery_address_id=None,
            pickup_post_data={
                f"pickup_location_{self.store.pk}": str(self.pickup.pk),
            },
        )
        self._login(self.user_a)
        response = self.client.get(self._detail_url(order.order_number))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pickup location")
        self.assertContains(response, self.pickup.name)
        self.assertContains(response, "Mon–Sat 9:00–20:00")

    def test_other_customers_order_number_returns_404(self):
        order_b = self._place_for(
            self.customer_b, self.user_b, token="tok-iso-b"
        )
        self._login(self.user_a)
        response = self.client.get(self._detail_url(order_b.order_number))
        self.assertEqual(response.status_code, 404)
        # Query-string spoofing cannot switch customer scope.
        response = self.client.get(
            self.list_url,
            {"customer_id": self.customer_b.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, order_b.order_number)

    def test_cancel_requires_post_and_csrf(self):
        order = self._place_for(
            self.customer_a, self.user_a, token="tok-cancel-method"
        )
        self._login(self.user_a)
        self.assertEqual(
            self.client.get(self._cancel_url(order.order_number)).status_code,
            405,
        )
        plain = Client(enforce_csrf_checks=True)
        plain.force_login(self.user_a)
        response = plain.post(
            self._cancel_url(order.order_number),
            {"reason": "No CSRF"},
        )
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_customer_can_cancel_own_order(self):
        order = self._place_for(
            self.customer_a, self.user_a, token="tok-cancel-own"
        )
        self._login(self.user_a)
        csrf = self.client.get(self._detail_url(order.order_number)).cookies[
            "csrftoken"
        ].value
        response = self.client.post(
            self._cancel_url(order.order_number),
            {
                "csrfmiddlewaretoken": csrf,
                "reason": "Changed my mind",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self._detail_url(order.order_number))
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.cancellation_reason, "Changed my mind")
        detail = self.client.get(self._detail_url(order.order_number))
        self.assertContains(detail, "Cancelled")
        self.assertContains(detail, "Changed my mind")

    def test_cannot_cancel_another_customers_order(self):
        order_b = self._place_for(
            self.customer_b, self.user_b, token="tok-cancel-iso"
        )
        self._login(self.user_a)
        csrf = self.client.get(self.list_url).cookies["csrftoken"].value
        response = self.client.post(
            self._cancel_url(order_b.order_number),
            {
                "csrfmiddlewaretoken": csrf,
                "reason": "Trying to cancel Bob",
            },
        )
        self.assertEqual(response.status_code, 404)
        order_b.refresh_from_db()
        self.assertEqual(order_b.status, OrderStatus.PLACED)
        self.assertFalse(order_b.cancellation_reason)

    def test_cancel_requires_reason(self):
        order = self._place_for(
            self.customer_a, self.user_a, token="tok-cancel-reason"
        )
        self._login(self.user_a)
        csrf = self.client.get(self._detail_url(order.order_number)).cookies[
            "csrftoken"
        ].value
        response = self.client.post(
            self._cancel_url(order.order_number),
            {"csrfmiddlewaretoken": csrf, "reason": "   "},
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PLACED)

    def test_nonexistent_order_number_is_404(self):
        self._login(self.user_a)
        self.assertEqual(
            self.client.get(self._detail_url("ORD-DOES-NOT-EXIST")).status_code,
            404,
        )
        csrf = self.client.get(self.list_url).cookies["csrftoken"].value
        self.assertEqual(
            self.client.post(
                self._cancel_url("ORD-DOES-NOT-EXIST"),
                {"csrfmiddlewaretoken": csrf, "reason": "x"},
            ).status_code,
            404,
        )

    def test_staff_user_without_customer_profile_denied(self):
        staff = User.objects.create_user(
            username="order-staff",
            email="order-staff@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (302, 403))
        if response.status_code == 302:
            self.assertIn("/customer/login/", response.url)

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
