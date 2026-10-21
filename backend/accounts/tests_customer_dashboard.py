from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Role
from customers.models import RegistrationSource, VerificationStatus
from customers.services import create_customer_with_user, get_customer_dashboard_stats

User = get_user_model()


class ManagementDashboardCustomerCardTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="cust-dash-super",
            email="cust-dash-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="cust-dash-admin",
            email="cust-dash-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.view_customer = Permission.objects.get(
            codename="view_customer",
            content_type__app_label="customers",
        )
        self.dashboard_url = reverse("accounts:management_dashboard")
        self.customers_url = reverse("customers:customer_list")

        # Website: 2 active unverified, 1 inactive unverified
        for index in range(1, 3):
            create_customer_with_user(
                user_data={
                    "username": f"web-active-{index}",
                    "email": f"web-active-{index}@example.com",
                    "first_name": "Web",
                    "last_name": f"Active{index}",
                    "phone_number": f"980000000{index}",
                    "password": "secure-password-123",
                },
                registration_source=RegistrationSource.WEBSITE,
            )
        inactive_web, inactive_user = create_customer_with_user(
            user_data={
                "username": "web-inactive",
                "email": "web-inactive@example.com",
                "first_name": "Web",
                "last_name": "Inactive",
                "phone_number": "9800000099",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        inactive_user.is_active = False
        inactive_user.save(update_fields=["is_active"])

        # Management: 2 active verified, 1 active unverified
        for index in range(1, 3):
            customer, _ = create_customer_with_user(
                user_data={
                    "username": f"mgmt-verified-{index}",
                    "email": f"mgmt-verified-{index}@example.com",
                    "first_name": "Mgmt",
                    "last_name": f"Verified{index}",
                    "phone_number": f"981000000{index}",
                    "password": "secure-password-123",
                },
                registration_source=RegistrationSource.MANAGEMENT_PORTAL,
                created_by=self.super_admin,
            )
            customer.verification_status = VerificationStatus.VERIFIED
            customer.save(update_fields=["verification_status", "updated_at"])

        create_customer_with_user(
            user_data={
                "username": "mgmt-unverified",
                "email": "mgmt-unverified@example.com",
                "first_name": "Mgmt",
                "last_name": "Unverified",
                "phone_number": "9810000099",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.MANAGEMENT_PORTAL,
            created_by=self.super_admin,
        )

        # Mobile app registration should count in total only
        create_customer_with_user(
            user_data={
                "username": "mobile-customer",
                "email": "mobile-customer@example.com",
                "first_name": "Mobile",
                "last_name": "Customer",
                "phone_number": "9820000001",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.MOBILE_APP,
        )

    def _assert_customer_card_counts(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customers")
        self.assertContains(response, f'href="{self.customers_url}"')
        stats = response.context["customer_stats"]
        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["active"], 6)
        self.assertEqual(stats["inactive"], 1)
        self.assertEqual(stats["verified"], 2)
        self.assertEqual(stats["unverified"], 5)
        self.assertEqual(stats["website"], 3)
        self.assertEqual(stats["management"], 3)
        self.assertContains(
            response, f"<strong>Total Customers:</strong> {stats['total']}"
        )
        self.assertContains(
            response, f"<strong>Active Customers:</strong> {stats['active']}"
        )
        self.assertContains(
            response, f"<strong>Inactive Customers:</strong> {stats['inactive']}"
        )
        self.assertContains(
            response, f"<strong>Verified Customers:</strong> {stats['verified']}"
        )
        self.assertContains(
            response,
            f"<strong>Unverified Customers:</strong> {stats['unverified']}",
        )
        self.assertContains(
            response,
            f"<strong>Website registrations:</strong> {stats['website']}",
        )
        self.assertContains(
            response,
            f"<strong>Management registrations:</strong> {stats['management']}",
        )

    def test_customer_card_hidden_for_admin_without_view_customer(self):
        self.client.login(username="cust-dash-admin", password="secure-password-123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["customer_stats"])
        self.assertNotContains(response, "Total Customers")
        self.assertNotContains(response, "Website registrations")
        self.assertNotContains(response, self.customers_url)
        customer_table_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "customers_customer" in query["sql"].lower()
        ]
        self.assertEqual(customer_table_queries, [])

    def test_customer_card_visible_with_counts_for_admin_with_view_customer(self):
        self.admin.user_permissions.add(self.view_customer)
        self.client.login(username="cust-dash-admin", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self._assert_customer_card_counts(response)

    def test_customer_card_visible_with_counts_for_super_admin(self):
        self.client.login(username="cust-dash-super", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self._assert_customer_card_counts(response)

    def test_customer_dashboard_stats_uses_single_aggregate_query(self):
        with CaptureQueriesContext(connection) as ctx:
            stats = get_customer_dashboard_stats()

        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["active"], 6)
        self.assertEqual(stats["inactive"], 1)
        self.assertEqual(stats["verified"], 2)
        self.assertEqual(stats["unverified"], 5)
        self.assertEqual(stats["website"], 3)
        self.assertEqual(stats["management"], 3)
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertIn("COUNT", ctx.captured_queries[0]["sql"].upper())
