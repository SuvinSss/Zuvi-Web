from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role

from .models import RegistrationSource, VerificationStatus
from .services import create_customer_with_user

User = get_user_model()


class CustomerPortalProfileTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "profile-customer-a",
                "email": "profile-a@example.com",
                "first_name": "Alice",
                "last_name": "Alpha",
                "phone_number": "9111111111",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "profile-customer-b",
                "email": "profile-b@example.com",
                "first_name": "Bob",
                "last_name": "Beta",
                "phone_number": "9222222222",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.MANAGEMENT_PORTAL,
            created_by=User.objects.create_user(
                username="profile-admin-creator",
                email="profile-admin-creator@example.com",
                password="secure-password-123",
                role=Role.ADMIN,
                is_staff=True,
            ),
        )
        self.customer_b.verification_status = VerificationStatus.VERIFIED
        self.customer_b.save(update_fields=["verification_status", "updated_at"])

    def _csrf_token(self, url):
        response = self.client.get(url)
        return response.cookies["csrftoken"].value













