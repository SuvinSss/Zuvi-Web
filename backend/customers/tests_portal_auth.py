from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role

from .models import RegistrationSource
from .services import create_customer_with_user

User = get_user_model()


class CustomerPortalAuthTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.customer, self.customer_user = create_customer_with_user(
            user_data={
                "username": "portal-customer",
                "email": "portal-customer@example.com",
                "first_name": "Pat",
                "last_name": "Customer",
                "phone_number": "9000000001",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )

        self.super_admin = User.objects.create_user(
            username="portal-super",
            email="portal-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="portal-admin",
            email="portal-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
        )
        self.store_user = User.objects.create_user(
            username="portal-store",
            email="portal-store@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        self.delivery_agent = User.objects.create_user(
            username="portal-delivery",
            email="portal-delivery@example.com",
            password="secure-password-123",
            role=Role.DELIVERY_AGENT,
        )
        self.customer_without_profile = User.objects.create_user(
            username="portal-customer-noprofile",
            email="portal-customer-noprofile@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )

    def _csrf_token(self, url):
        response = self.client.get(url)
        return response.cookies["csrftoken"].value
















