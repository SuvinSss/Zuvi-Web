from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cart.models import CartItem
from cart.services import get_cart_item_count, get_or_create_cart_for_customer
from orders.models import OrderStatus
from orders.tests import OrderModelTestMixin

from .models import AddressLabel, RegistrationSource, VerificationStatus
from .services import (
    create_customer_with_user,
    get_customer_portal_dashboard_context,
    get_customer_profile_completion_message,
)
from .tests import CustomerModelTestMixin

User = get_user_model()


class CustomerPortalDashboardTests(CustomerModelTestMixin, TestCase):
    def setUp(self):

        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "dash-customer-a",
                "email": "dash-a@example.com",
                "first_name": "Alice",
                "last_name": "Alpha",
                "phone_number": "9111111111",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "dash-customer-b",
                "email": "dash-b@example.com",
                "first_name": "Bob",
                "last_name": "Beta",
                "phone_number": "9222222222",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address_a = self.create_customer_address(
            self.customer_a,
            label=AddressLabel.HOME,
            recipient_name="Alice Alpha",
            phone_number="9111111111",
            is_default=True,
            address=self.create_address(
                line1="10 Alice Street",
                city="Bengaluru",
                postal_code="560001",
            ),
        )
        self.address_a_secondary = self.create_customer_address(
            self.customer_a,
            label=AddressLabel.WORK,
            recipient_name="Alice Work",
            phone_number="9111111111",
            is_default=False,
            address=self.create_address(
                line1="20 Alice Office",
                city="Bengaluru",
                postal_code="560002",
            ),
        )
        self.address_b = self.create_customer_address(
            self.customer_b,
            label=AddressLabel.HOME,
            recipient_name="Bob Beta Secret",
            phone_number="9222222222",
            is_default=True,
            address=self.create_address(
                line1="99 Bob Secret Lane",
                city="Mysuru",
                postal_code="570001",
            ),
        )





    def test_inactive_addresses_are_not_counted(self):
        self.create_customer_address(
            self.customer_a,
            label=AddressLabel.OTHER,
            recipient_name="Inactive Addr",
            is_default=False,
            is_active=False,
            address=self.create_address(line1="Inactive Road"),
        )
        context = get_customer_portal_dashboard_context(self.user_a)
        self.assertEqual(context["saved_address_count"], 2)
        self.assertEqual(context["default_address"].pk, self.address_a.pk)

    def test_context_builder_uses_authenticated_user_only(self):
        context = get_customer_portal_dashboard_context(self.user_a)
        self.assertEqual(context["customer"].user_id, self.user_a.pk)
        self.assertNotEqual(context["customer"].pk, self.customer_b.pk)
        self.assertEqual(context["default_address"].recipient_name, "Alice Alpha")

    def test_profile_completion_message_variants(self):
        user = User(first_name="", last_name="", phone_number="")
        self.assertEqual(
            get_customer_profile_completion_message(
                user=user,
                has_default_address=False,
            ),
            "Complete your profile by adding your full name, a phone number, "
            "and a default delivery address.",
        )
        user = User(first_name="Pat", last_name="Customer", phone_number="9000000000")
        self.assertEqual(
            get_customer_profile_completion_message(
                user=user,
                has_default_address=True,
            ),
            "Your profile is complete.",
        )



class CustomerPortalOrderDashboardTests(OrderModelTestMixin, TestCase):
    def setUp(self):
        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "dash-ord-a",
                "email": "dash-ord-a@example.com",
                "first_name": "Alice",
                "last_name": "Orders",
                "phone_number": "9333333333",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "dash-ord-b",
                "email": "dash-ord-b@example.com",
                "first_name": "Bob",
                "last_name": "Orders",
                "phone_number": "9444444444",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.create_customer_address(
            self.customer_a,
            label=AddressLabel.HOME,
            recipient_name="Alice Orders",
            phone_number="9333333333",
            is_default=True,
        )

        product = self.create_product(store=self.create_store(name="Dash Cart Store"))
        cart_a = get_or_create_cart_for_customer(self.customer_a)
        CartItem.objects.create(
            cart=cart_a, product=product, quantity=Decimal("2.000")
        )
        CartItem.objects.create(
            cart=cart_a,
            product=self.create_product(store=product.store, sku="CART-2"),
            quantity=Decimal("1.000"),
        )
        cart_b = get_or_create_cart_for_customer(self.customer_b)
        CartItem.objects.create(
            cart=cart_b,
            product=self.create_product(store=self.create_store(name="Other Store")),
            quantity=Decimal("9.000"),
        )

        self.pending_a = self.create_delivery_order(
            customer=self.customer_a,
            status=OrderStatus.PLACED,
            grand_total=Decimal("10.00"),
        )
        self.completed_a = self.create_delivery_order(
            customer=self.customer_a,
            status=OrderStatus.COMPLETED,
            grand_total=Decimal("20.00"),
        )
        self.pending_b = self.create_delivery_order(
            customer=self.customer_b,
            status=OrderStatus.PLACED,
            grand_total=Decimal("99.00"),
        )

    def test_cart_item_count_is_customer_scoped(self):
        self.assertEqual(get_cart_item_count(self.customer_a), 2)
        self.assertEqual(get_cart_item_count(self.customer_b), 1)


