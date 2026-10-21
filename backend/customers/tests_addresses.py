from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from .decorators import portal_customer_addresses_queryset
from .models import AddressLabel, RegistrationSource
from .services import (
    create_customer_delivery_address,
    create_customer_with_user,
    deactivate_customer_address,
    update_customer_delivery_address,
)
from .tests import CustomerModelTestMixin


class CustomerPortalAddressTests(CustomerModelTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "addr-customer-a",
                "email": "addr-a@example.com",
                "first_name": "Alice",
                "last_name": "Alpha",
                "phone_number": "9111111111",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "addr-customer-b",
                "email": "addr-b@example.com",
                "first_name": "Bob",
                "last_name": "Beta",
                "phone_number": "9222222222",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )

        self.valid_payload = {
            "label": AddressLabel.HOME,
            "recipient_name": "Alice Alpha",
            "phone_number": "9111111111",
            "line1": "10 Alice Street",
            "line2": "Apt 2",
            "landmark": "Near Park",
            "city": "Bengaluru",
            "district": "Bengaluru Urban",
            "state": "Karnataka",
            "postal_code": "560001",
            "latitude": "12.971600",
            "longitude": "77.594600",
            "delivery_instructions": "Ring the bell",
            "is_default": "on",
        }

    def _csrf_token(self, url):
        response = self.client.get(url)
        return response.cookies["csrftoken"].value










    def test_deactivate_only_address_leaves_no_default(self):
        only = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Alone",
                "phone_number": "9111111111",
                "line1": "Solo Street",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        deactivate_customer_address(customer_address=only)
        only.refresh_from_db()
        self.assertFalse(only.is_active)
        self.assertFalse(only.is_default)
        self.assertFalse(
            self.customer_a.addresses.filter(is_active=True, is_default=True).exists()
        )









    def test_clearing_default_on_edit_promotes_another_active_address(self):
        first = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Home",
                "phone_number": "9111111111",
                "line1": "Home Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        second = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.WORK,
                "recipient_name": "Alice Work",
                "phone_number": "9111111111",
                "line1": "Work Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560002",
                "latitude": Decimal("12.980000"),
                "longitude": Decimal("77.600000"),
                "delivery_instructions": "",
                "is_default": False,
            },
        )

        update_customer_delivery_address(
            customer_address=first,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Home",
                "phone_number": "9111111111",
                "line1": "Home Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": False,
            },
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(
            self.customer_a.addresses.filter(is_active=True, is_default=True).count(),
            1,
        )
