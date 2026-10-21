"""
Management portal Order permissions and access control.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from cart.services import add_product_to_cart
from customers.models import AddressLabel, RegistrationSource
from customers.services import create_customer_delivery_address, create_customer_with_user
from stores.models import StoreUser

from .checkout import place_customer_order
from .decorators import user_has_order_permission
from .models import FulfillmentType, OrderStatus, PaymentMethod, PaymentStatus
from .tests_checkout import CheckoutTestMixin

User = get_user_model()


class OrderPermissionTestMixin(CheckoutTestMixin):
    def create_super_admin(self, username="order-super"):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def create_admin(self, username="order-admin"):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
        )

    def create_store_user(self, *, store, username="order-store-user"):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=store,
            user=user,
            is_primary=True,
            is_active=True,
            can_manage_orders=True,
        )
        return user

    def grant_order_perms(self, user, *codenames):
        for codename in codenames:
            permission = Permission.objects.get(
                content_type__app_label="orders",
                codename=codename,
            )
            user.user_permissions.add(permission)
        return User.objects.get(pk=user.pk)

    def place_sample_order(self, *, token="tok-mgmt-order"):
        add_product_to_cart(
            customer=self.customer,
            product_code=self.product.product_code,
            quantity=Decimal("2.000"),
        )
        return place_customer_order(
            customer=self.customer,
            checkout_token=token,
            fulfillment_type=FulfillmentType.DELIVERY,
            payment_method=PaymentMethod.COD,
            delivery_address_id=self.address.pk,
            actor=self.customer_user,
        )


class OrderPermissionHelperTests(OrderPermissionTestMixin, TestCase):
    def setUp(self):
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()
        self.store = self.create_store(name="Perm Store")
        self.store_user = self.create_store_user(store=self.store)
        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "order-end-customer",
                "email": "order-end@example.com",
                "first_name": "End",
                "last_name": "Customer",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )

    def test_cancel_order_permission_exists(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="orders",
                codename="cancel_order",
            ).exists()
        )
        for codename in ("view_order", "change_order"):
            self.assertTrue(
                Permission.objects.filter(
                    content_type__app_label="orders",
                    codename=codename,
                ).exists()
            )

    def test_super_admin_bypasses_order_permissions(self):
        for perm in (
            "orders.view_order",
            "orders.change_order",
            "orders.cancel_order",
            "orders.manage_payment_status",
        ):
            self.assertTrue(user_has_order_permission(self.super_admin, perm))

    def test_admin_without_permissions_denied(self):
        for perm in (
            "orders.view_order",
            "orders.change_order",
            "orders.cancel_order",
        ):
            self.assertFalse(user_has_order_permission(self.admin, perm))

    def test_admin_with_granted_permission(self):
        self.admin = self.grant_order_perms(self.admin, "view_order")
        self.assertTrue(
            user_has_order_permission(self.admin, "orders.view_order")
        )
        self.assertFalse(
            user_has_order_permission(self.admin, "orders.change_order")
        )

    def test_store_user_and_customer_never_pass_management_helper(self):
        for user in (self.store_user, self.customer_user):
            user = self.grant_order_perms(
                user,
                "view_order",
                "change_order",
                "cancel_order",
            )
            for perm in (
                "orders.view_order",
                "orders.change_order",
                "orders.cancel_order",
            ):
                self.assertFalse(
                    user_has_order_permission(user, perm),
                    msg=f"{user.role} must not pass management check for {perm}",
                )


class OrderManagementPermissionViewTests(OrderPermissionTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()
        self.store = self.create_store(name="Mgmt Order Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Mgmt Item",
            stock=Decimal("20.000"),
            store_price=Decimal("40.00"),
            profit_margin=Decimal("10.00"),
        )
        self.store_user = self.create_store_user(
            store=self.store,
            username="mgmt-store-user",
        )
        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "mgmt-order-customer",
                "email": "mgmt-order-customer@example.com",
                "first_name": "Mgmt",
                "last_name": "Customer",
                "phone_number": "9000000955",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Mgmt Customer",
                "phone_number": "9000000955",
                "line1": "1 Mgmt Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self.order = self.place_sample_order()
        self.store_order = self.order.store_orders.get()
        self.list_url = reverse("orders:management_order_list")
        self.detail_url = reverse(
            "orders:management_order_detail",
            kwargs={"order_number": self.order.order_number},
        )
        self.change_url = reverse(
            "orders:management_order_change_status",
            kwargs={"order_number": self.order.order_number},
        )
        self.store_order_url = reverse(
            "orders:management_store_order_detail",
            kwargs={"store_order_number": self.store_order.store_order_number},
        )

    def _login_admin_with(self, *codenames):
        self.admin = self.grant_order_perms(self.admin, *codenames)
        self.client.login(username="order-admin", password="secure-password-123")

    def _csrf(self):
        return self.client.get(self.detail_url).cookies["csrftoken"].value

    def test_super_admin_can_view_and_mutate(self):
        self.client.login(username="order-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.store_order_url).status_code, 200)

        csrf = self._csrf()
        response = self.client.post(
            self.change_url,
            {
                "csrfmiddlewaretoken": csrf,
                "action": "update_status",
                "status-status": OrderStatus.CONFIRMED,
                "status-reason": "Confirmed by super",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CONFIRMED)

    def test_admin_requires_view_order_to_list_and_detail(self):
        self.client.login(username="order-admin", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_order_url).status_code, 403)

        self._login_admin_with("view_order")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        detail = self.client.get(self.detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, self.order.order_number)
        self.assertContains(detail, self.store_order.store_order_number)
        self.assertEqual(self.client.get(self.store_order_url).status_code, 200)

    def test_admin_requires_change_order_for_status_update(self):
        self._login_admin_with("view_order")
        csrf = self._csrf()
        response = self.client.post(
            self.change_url,
            {
                "csrfmiddlewaretoken": csrf,
                "action": "update_status",
                "status-status": OrderStatus.CONFIRMED,
                "status-reason": "No change perm",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PLACED)

        self._login_admin_with("view_order", "change_order")
        csrf = self._csrf()
        response = self.client.post(
            self.change_url,
            {
                "csrfmiddlewaretoken": csrf,
                "action": "update_status",
                "status-status": OrderStatus.CONFIRMED,
                "status-reason": "Allowed",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CONFIRMED)

    def test_admin_requires_cancel_order_for_cancellation(self):
        self._login_admin_with("view_order", "change_order")
        csrf = self._csrf()
        response = self.client.post(
            self.change_url,
            {
                "csrfmiddlewaretoken": csrf,
                "action": "cancel",
                "cancel-reason": "Should be denied",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PLACED)

        self._login_admin_with("view_order", "cancel_order")
        csrf = self._csrf()
        response = self.client.post(
            self.change_url,
            {
                "csrfmiddlewaretoken": csrf,
                "action": "cancel",
                "cancel-reason": "Admin cancellation",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.order.payment_status, PaymentStatus.CANCELLED)

    def test_state_change_requires_post(self):
        self._login_admin_with("view_order", "change_order")
        response = self.client.get(self.change_url)
        self.assertEqual(response.status_code, 405)

    def test_store_user_and_customer_cannot_access_management_orders(self):
        self.client.login(username="mgmt-store-user", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_order_url).status_code, 403)

        self.client.logout()
        self.client.login(
            username="mgmt-order-customer",
            password="secure-password-123",
        )
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url).status_code, 403)
        self.assertEqual(self.client.get(self.store_order_url).status_code, 403)

    def test_list_search_and_filters(self):
        self._login_admin_with("view_order")
        response = self.client.get(
            self.list_url,
            {
                "q": self.order.order_number,
                "status": OrderStatus.PLACED,
                "store": self.store.pk,
                "customer": self.customer.pk,
                "fulfillment_type": FulfillmentType.DELIVERY,
                "payment_method": PaymentMethod.COD,
                "payment_status": PaymentStatus.PENDING,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Mgmt Customer")

        response = self.client.get(
            self.list_url,
            {"q": self.store_order.store_order_number},
        )
        self.assertContains(response, self.order.order_number)

        response = self.client.get(self.list_url, {"q": "no-such-order-xyz"})
        self.assertNotContains(response, self.order.order_number)

    def test_dashboard_orders_module_links_when_permitted(self):
        dashboard = reverse("accounts:management_dashboard")
        self.client.login(username="order-admin", password="secure-password-123")
        response = self.client.get(dashboard)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("orders:management_order_list"))

        self._login_admin_with("view_order")
        response = self.client.get(dashboard)
        self.assertContains(response, reverse("orders:management_order_list"))


class ManagementStatusRuleTests(OrderPermissionTestMixin, TestCase):
    def setUp(self):
        self.super_admin = self.create_super_admin()
        self.store = self.create_store(name="Status Rule Store")
        self.product = self.create_public_product(
            store=self.store,
            name="Status Product",
            stock=Decimal("5.000"),
        )
        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "status-rule-customer",
                "email": "status-rule@example.com",
                "first_name": "Status",
                "last_name": "Customer",
                "phone_number": "9000000999",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Status Customer",
                "phone_number": "9000000999",
                "line1": "1 Rule St",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self.order = self.place_sample_order(token="tok-status-rules")
        self.store_order = self.order.store_orders.get()

    def test_payment_collected_requires_completed_order(self):
        from django.core.exceptions import ValidationError

        from .management_status import (
            available_admin_payment_statuses,
            update_order_payment_status,
            update_order_status,
        )
        from .models import StoreOrderStatus

        self.assertNotIn(
            PaymentStatus.COLLECTED,
            available_admin_payment_statuses(self.order),
        )
        with self.assertRaises(ValidationError):
            update_order_payment_status(
                order=self.order,
                new_payment_status=PaymentStatus.COLLECTED,
                actor=self.super_admin,
                reason="Too early",
            )

        self.order.status = OrderStatus.IN_PROGRESS
        self.order.save(update_fields=["status", "updated_at"])
        self.store_order.status = StoreOrderStatus.READY
        self.store_order.save(update_fields=["status", "updated_at"])

        update_order_status(
            order=self.order,
            new_status=OrderStatus.COMPLETED,
            actor=self.super_admin,
            reason="Delivered",
        )
        self.order.refresh_from_db()
        self.store_order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.store_order.status, StoreOrderStatus.COMPLETED)

        update_order_payment_status(
            order=self.order,
            new_payment_status=PaymentStatus.COLLECTED,
            actor=self.super_admin,
            reason="Cash received",
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.COLLECTED)

    def test_cannot_complete_order_while_store_order_pending(self):
        from django.core.exceptions import ValidationError

        from .management_status import (
            available_admin_order_statuses,
            update_order_status,
        )

        self.order.status = OrderStatus.CONFIRMED
        self.order.save(update_fields=["status", "updated_at"])
        self.assertNotIn(
            OrderStatus.COMPLETED,
            available_admin_order_statuses(self.order),
        )
        with self.assertRaises(ValidationError):
            update_order_status(
                order=self.order,
                new_status=OrderStatus.COMPLETED,
                actor=self.super_admin,
                reason="Premature",
            )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CONFIRMED)
