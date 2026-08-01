"""
Store portal StoreOrder management and cross-store isolation.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from stores.models import StoreStatus, StoreUser

from .checkout import place_customer_order
from .models import FulfillmentType, PaymentMethod, StoreOrderStatus
from .store_status import transition_store_order
from .tests_checkout import CheckoutTestMixin

User = get_user_model()


class StoreOrderPortalIsolationTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.store_a = self.create_store(name="Orders Store A")
        self.store_b = self.create_store(name="Orders Store B")
        self.product_a = self.create_public_product(
            store=self.store_a,
            name="Alpha Order Item",
            stock=Decimal("20.000"),
            store_price=Decimal("50.00"),
            profit_margin=Decimal("10.00"),
        )
        self.product_b = self.create_public_product(
            store=self.store_b,
            name="Beta Order Item",
            stock=Decimal("20.000"),
            store_price=Decimal("40.00"),
            profit_margin=Decimal("10.00"),
        )

        self.manager_a = User.objects.create_user(
            username="orders-mgr-a",
            email="orders-mgr-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.manager_a,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
            can_manage_orders=True,
        )
        self.viewer_a = User.objects.create_user(
            username="orders-viewer-a",
            email="orders-viewer-a@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.viewer_a,
            is_primary=False,
            is_active=True,
            can_manage_inventory=True,
            can_manage_orders=False,
        )
        self.manager_b = User.objects.create_user(
            username="orders-mgr-b",
            email="orders-mgr-b@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.manager_b,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
            can_manage_orders=True,
        )

        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "store-order-customer",
                "email": "store-order-customer@example.com",
                "first_name": "Store",
                "last_name": "Customer",
                "phone_number": "9000000911",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Store Customer",
                "phone_number": "9000000911",
                "line1": "15 Portal Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "Leave at gate",
                "is_default": True,
            },
        )

        self.list_url = reverse("orders:store_order_list")
        self.login_url = reverse("stores:store_portal_login")

    def _login(self, user):
        self.client.force_login(user)
        self.client.get(reverse("stores:store_portal_dashboard"))

    def _place_multi_store(self, *, token):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_a.product_code,
            quantity=Decimal("2.000"),
        )
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product_b.product_code,
            quantity=Decimal("1.000"),
        )
        return place_customer_order(
            customer=self.customer,
            checkout_token=token,
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            customer_notes="Please pack carefully",
            actor=self.customer_user,
        )

    def _detail_url(self, number):
        return reverse(
            "orders:store_order_detail",
            kwargs={"store_order_number": number},
        )

    def _action_url(self, name, number):
        return reverse(
            f"orders:{name}",
            kwargs={"store_order_number": number},
        )

    def test_list_shows_only_own_store_orders(self):
        order = self._place_multi_store(token="tok-store-list")
        so_a = order.store_orders.get(store=self.store_a)
        so_b = order.store_orders.get(store=self.store_b)

        self._login(self.manager_a)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, so_a.store_order_number)
        self.assertContains(response, order.order_number)
        self.assertContains(response, "Please pack carefully")
        self.assertNotContains(response, so_b.store_order_number)
        # Forged store_id query must not leak Store B.
        response = self.client.get(self.list_url, {"store_id": self.store_b.pk})
        self.assertNotContains(response, so_b.store_order_number)

    def test_detail_isolation_and_content(self):
        order = self._place_multi_store(token="tok-store-detail")
        so_a = order.store_orders.get(store=self.store_a)
        so_b = order.store_orders.get(store=self.store_b)

        self._login(self.manager_a)
        response = self.client.get(self._detail_url(so_a.store_order_number))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Order Item")
        self.assertContains(response, "15 Portal Lane")
        self.assertContains(response, f"₹{self.product_a.final_price}")
        self.assertNotContains(response, "store_price")
        self.assertNotContains(response, "profit_margin")
        self.assertNotContains(response, str(self.product_a.store_price))

        # Store A cannot open Store B's order number.
        self.assertEqual(
            self.client.get(self._detail_url(so_b.store_order_number)).status_code,
            404,
        )

    def test_status_actions_require_post_and_permission(self):
        order = self._place_multi_store(token="tok-store-post")
        so_a = order.store_orders.get(store=self.store_a)
        accept_url = self._action_url("store_order_accept", so_a.store_order_number)

        self._login(self.manager_a)
        self.assertEqual(self.client.get(accept_url).status_code, 405)

        # Viewer without can_manage_orders may view but not mutate.
        self._login(self.viewer_a)
        self.assertEqual(
            self.client.get(self._detail_url(so_a.store_order_number)).status_code,
            200,
        )
        csrf = self.client.get(self._detail_url(so_a.store_order_number)).cookies[
            "csrftoken"
        ].value
        response = self.client.post(
            accept_url,
            {"csrfmiddlewaretoken": csrf, "note-reason": ""},
        )
        self.assertEqual(response.status_code, 403)
        so_a.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.PENDING)

    def test_accept_processing_ready_and_invalid_transition(self):
        order = self._place_multi_store(token="tok-store-flow")
        so_a = order.store_orders.get(store=self.store_a)
        self._login(self.manager_a)

        def post(action_name, extra=None):
            csrf = self.client.get(
                self._detail_url(so_a.store_order_number)
            ).cookies["csrftoken"].value
            data = {"csrfmiddlewaretoken": csrf, "note-reason": "ok"}
            if extra:
                data.update(extra)
            return self.client.post(
                self._action_url(action_name, so_a.store_order_number),
                data,
            )

        self.assertEqual(post("store_order_accept").status_code, 302)
        so_a.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.ACCEPTED)

        # Cannot jump to ready from ACCEPTED.
        response = post("store_order_ready")
        self.assertEqual(response.status_code, 302)
        so_a.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.ACCEPTED)

        self.assertEqual(post("store_order_processing").status_code, 302)
        so_a.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.PREPARING)

        self.assertEqual(post("store_order_ready").status_code, 302)
        so_a.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.READY)

        # Invalid further accept.
        with self.assertRaises(ValidationError):
            transition_store_order(
                store_order=so_a,
                store=self.store_a,
                action="accept",
                actor=self.manager_a,
            )

    def test_reject_requires_reason_and_isolates_stock(self):
        order = self._place_multi_store(token="tok-store-reject")
        so_a = order.store_orders.get(store=self.store_a)
        so_b = order.store_orders.get(store=self.store_b)
        self.product_a.refresh_from_db()
        stock_a_before = self.product_a.stock_quantity
        self.product_b.refresh_from_db()
        stock_b_before = self.product_b.stock_quantity

        self._login(self.manager_a)
        csrf = self.client.get(self._detail_url(so_a.store_order_number)).cookies[
            "csrftoken"
        ].value
        # Missing reason.
        response = self.client.post(
            self._action_url("store_order_reject", so_a.store_order_number),
            {"csrfmiddlewaretoken": csrf, "reject-reason": "  "},
        )
        self.assertEqual(response.status_code, 302)
        so_a.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.PENDING)

        csrf = self.client.get(self._detail_url(so_a.store_order_number)).cookies[
            "csrftoken"
        ].value
        response = self.client.post(
            self._action_url("store_order_reject", so_a.store_order_number),
            {
                "csrfmiddlewaretoken": csrf,
                "reject-reason": "Out of stock locally",
            },
        )
        self.assertEqual(response.status_code, 302)
        so_a.refresh_from_db()
        so_b.refresh_from_db()
        self.assertEqual(so_a.status, StoreOrderStatus.REJECTED)
        self.assertEqual(so_b.status, StoreOrderStatus.PENDING)
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(
            self.product_a.stock_quantity,
            stock_a_before + Decimal("2.000"),
        )
        self.assertEqual(self.product_b.stock_quantity, stock_b_before)

        # Store A cannot reject Store B's order.
        csrf = self.client.get(self.list_url).cookies["csrftoken"].value
        response = self.client.post(
            self._action_url("store_order_reject", so_b.store_order_number),
            {
                "csrfmiddlewaretoken": csrf,
                "reject-reason": "Cross store",
            },
        )
        self.assertEqual(response.status_code, 404)
        so_b.refresh_from_db()
        self.assertEqual(so_b.status, StoreOrderStatus.PENDING)

    def test_suspended_store_cannot_access_orders(self):
        order = self._place_multi_store(token="tok-store-suspend")
        so_a = order.store_orders.get(store=self.store_a)
        self.store_a.status = StoreStatus.SUSPENDED
        self.store_a.save(update_fields=["status", "updated_at"])

        self._login(self.manager_a)
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (302, 403))
        response = self.client.get(self._detail_url(so_a.store_order_number))
        self.assertIn(response.status_code, (302, 403))

    def test_anonymous_redirected_to_store_login(self):
        client = Client()
        response = client.get(self.list_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/store/login/", response.url)
