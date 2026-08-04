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
        self.login_url = reverse("customers:customer_portal_login")
        self.logout_url = reverse("customers:customer_portal_logout")
        self.dashboard_url = reverse("customers:customer_portal_dashboard")

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

    def _login(self, username, password="secure-password-123"):
        token = self._csrf_token(self.login_url)
        return self.client.post(
            self.login_url,
            {
                "username": username,
                "password": password,
                "csrfmiddlewaretoken": token,
            },
        )

    def test_login_page_includes_csrf(self):
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Sign in")

    def test_active_customer_can_login_and_see_dashboard(self):
        response = self._login("portal-customer")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)
        self.assertIn("_auth_user_id", self.client.session)

        dashboard = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, self.customer.customer_code)
        self.assertContains(dashboard, "Pat Customer")
        self.assertContains(dashboard, "portal-customer@example.com")
        self.assertIn("no-store", dashboard.get("Cache-Control", ""))

    def test_super_admin_cannot_login_to_customer_portal(self):
        response = self._login("portal-super")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only Customers")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_cannot_login_to_customer_portal(self):
        response = self._login("portal-admin")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only Customers")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_store_user_cannot_login_to_customer_portal(self):
        response = self._login("portal-store")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only Customers")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_delivery_agent_cannot_login_to_customer_portal(self):
        response = self._login("portal-delivery")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only Customers")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_customer_without_profile_cannot_login(self):
        response = self._login("portal-customer-noprofile")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No customer profile")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_customer_cannot_login(self):
        self.customer_user.is_active = False
        self.customer_user.save(update_fields=["is_active"])
        response = self._login("portal-customer")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        dashboard = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/customer/login/", dashboard.url)

    def test_anonymous_redirected_to_customer_login(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/customer/login/", response.url)

    def test_logout_requires_post(self):
        self._login("portal-customer")
        self.assertEqual(self.client.get(self.logout_url).status_code, 405)

        token = self._csrf_token(self.dashboard_url)
        response = self.client.post(
            self.logout_url,
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.login_url)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_rejects_missing_csrf(self):
        plain_client = Client(enforce_csrf_checks=True)
        login_response = plain_client.post(
            self.login_url,
            {
                "username": "portal-customer",
                "password": "secure-password-123",
                "csrfmiddlewaretoken": plain_client.get(self.login_url).cookies[
                    "csrftoken"
                ].value,
            },
        )
        self.assertEqual(login_response.status_code, 302)
        response = plain_client.post(self.logout_url, {})
        self.assertEqual(response.status_code, 403)

    def test_protected_pages_inaccessible_after_logout(self):
        self._login("portal-customer")
        token = self._csrf_token(self.dashboard_url)
        self.client.post(self.logout_url, {"csrfmiddlewaretoken": token})

        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/customer/login/", response.url)

    def test_authenticated_wrong_role_denied_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_authenticated_customer_without_profile_denied_dashboard(self):
        self.client.force_login(self.customer_without_profile)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_authenticated_customer_redirected_from_login_to_dashboard(self):
        self._login("portal-customer")
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)
