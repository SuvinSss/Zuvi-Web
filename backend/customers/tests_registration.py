from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role

from .models import Customer, CustomerAddress, RegistrationSource, VerificationStatus

User = get_user_model()


class CustomerSelfRegistrationTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.valid_payload = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "username": "ada-customer",
            "email": "ada@example.com",
            "phone_number": "9876543210",
            "password": "secure-password-123",
            "confirm_password": "secure-password-123",
            "accept_terms": "on",
        }










    def test_service_strips_privilege_fields_from_user_data(self):
        from .services import create_customer_with_user

        customer, user = create_customer_with_user(
            user_data={
                "username": "service-user",
                "email": "service@example.com",
                "first_name": "Service",
                "last_name": "User",
                "phone_number": "9111111111",
                "password": "secure-password-123",
                "role": Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
            registration_source=RegistrationSource.WEBSITE,
            created_by=None,
        )
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(customer.registration_source, RegistrationSource.WEBSITE)
