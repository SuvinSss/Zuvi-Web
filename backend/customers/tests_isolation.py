from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role

from .models import AddressLabel, RegistrationSource, VerificationStatus
from .services import create_customer_delivery_address, create_customer_with_user

User = get_user_model()


class CustomerIsolationTests(TestCase):
    """
    End-to-end isolation checks for Customer A / Address A vs Customer B / Address B.
    """

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

        self.customer_a, self.user_a = create_customer_with_user(
            user_data={
                "username": "iso-customer-a",
                "email": "iso-a@example.com",
                "first_name": "Alice",
                "last_name": "Alpha",
                "phone_number": "9000000001",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address_a = create_customer_delivery_address(
            customer=self.customer_a,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Alice Alpha",
                "phone_number": "9000000001",
                "line1": "10 Alice Street",
                "line2": "",
                "landmark": "Alice Park",
                "city": "Bengaluru",
                "district": "Bengaluru Urban",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "Alice only",
                "is_default": True,
            },
        )

        self.customer_b, self.user_b = create_customer_with_user(
            user_data={
                "username": "iso-customer-b",
                "email": "iso-b@example.com",
                "first_name": "Bob",
                "last_name": "Beta",
                "phone_number": "9000000002",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.customer_b.verification_status = VerificationStatus.VERIFIED
        self.customer_b.save(update_fields=["verification_status", "updated_at"])
        self.address_b = create_customer_delivery_address(
            customer=self.customer_b,
            data={
                "label": AddressLabel.WORK,
                "recipient_name": "Bob Beta Secret",
                "phone_number": "9000000002",
                "line1": "99 Bob Secret Lane",
                "line2": "",
                "landmark": "Hidden Landmark",
                "city": "Mysuru",
                "district": "Mysuru",
                "state": "Karnataka",
                "postal_code": "570001",
                "latitude": Decimal("12.295800"),
                "longitude": Decimal("76.639400"),
                "delivery_instructions": "Do not share",
                "is_default": True,
            },
        )

        self.store_user = User.objects.create_user(
            username="iso-store-user",
            email="iso-store@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        self.delivery_agent = User.objects.create_user(
            username="iso-delivery-agent",
            email="iso-delivery@example.com",
            password="secure-password-123",
            role=Role.DELIVERY_AGENT,
        )

        self.login_url = reverse("customers:customer_portal_login")
        self.dashboard_url = reverse("customers:customer_portal_dashboard")
        self.profile_url = reverse("customers:customer_portal_profile")
        self.profile_edit_url = reverse("customers:customer_portal_profile_edit")
        self.address_list_url = reverse("customers:customer_portal_address_list")
        self.address_a_edit_url = reverse(
            "customers:customer_portal_address_edit",
            kwargs={"pk": self.address_a.pk},
        )
        self.address_b_edit_url = reverse(
            "customers:customer_portal_address_edit",
            kwargs={"pk": self.address_b.pk},
        )
        self.address_b_set_default_url = reverse(
            "customers:customer_portal_address_set_default",
            kwargs={"pk": self.address_b.pk},
        )
        self.address_b_deactivate_url = reverse(
            "customers:customer_portal_address_deactivate",
            kwargs={"pk": self.address_b.pk},
        )
        self.address_a_set_default_url = reverse(
            "customers:customer_portal_address_set_default",
            kwargs={"pk": self.address_a.pk},
        )
        self.address_a_deactivate_url = reverse(
            "customers:customer_portal_address_deactivate",
            kwargs={"pk": self.address_a.pk},
        )

    def _csrf(self, url):
        return self.client.get(url).cookies["csrftoken"].value

    def _login(self, user):
        self.client.force_login(user)
        self.client.get(self.dashboard_url)

    def _post(self, url, payload=None, *, seed_url=None):
        token = self._csrf(seed_url or self.dashboard_url)
        data = dict(payload or {})
        data["csrfmiddlewaretoken"] = token
        return self.client.post(url, data)

    def test_01_customer_a_can_view_and_edit_own_profile(self):
        self._login(self.user_a)

        view = self.client.get(self.profile_url)
        self.assertEqual(view.status_code, 200)
        self.assertContains(view, "Alice")
        self.assertContains(view, "Alpha")
        self.assertContains(view, self.customer_a.customer_code)
        self.assertContains(view, "iso-a@example.com")
        self.assertNotContains(view, self.customer_b.customer_code)
        self.assertNotContains(view, "Bob")

        edit_get = self.client.get(self.profile_edit_url)
        self.assertEqual(edit_get.status_code, 200)
        self.assertContains(edit_get, self.customer_a.customer_code)

        edit_post = self._post(
            self.profile_edit_url,
            {
                "first_name": "Alicia",
                "last_name": "Alpha",
                "email": "iso-a-updated@example.com",
                "phone_number": "9000000001",
            },
            seed_url=self.profile_edit_url,
        )
        self.assertEqual(edit_post.status_code, 302)
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.first_name, "Alicia")
        self.assertEqual(self.user_a.email, "iso-a-updated@example.com")

    def test_02_customer_a_cannot_view_customer_b_profile(self):
        self._login(self.user_a)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["customer"].pk, self.customer_a.pk)
        self.assertNotContains(response, self.customer_b.customer_code)
        self.assertNotContains(response, "iso-b@example.com")
        self.assertNotContains(response, "Bob Beta Secret")

        # Profile routes are not keyed by customer_id; query param must be ignored.
        sneaky = self.client.get(
            self.profile_url,
            {"customer_id": self.customer_b.pk, "pk": self.customer_b.pk},
        )
        self.assertEqual(sneaky.status_code, 200)
        self.assertEqual(sneaky.context["customer"].pk, self.customer_a.pk)
        self.assertNotContains(sneaky, self.customer_b.customer_code)

    def test_03_customer_a_cannot_edit_customer_b_data(self):
        self._login(self.user_a)
        response = self._post(
            self.profile_edit_url,
            {
                "customer_id": self.customer_b.pk,
                "first_name": "Hacked",
                "last_name": "Bob",
                "email": "hacked-b@example.com",
                "phone_number": "9000000099",
            },
            seed_url=self.profile_edit_url,
        )
        self.assertEqual(response.status_code, 302)

        self.user_a.refresh_from_db()
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_a.first_name, "Hacked")
        self.assertEqual(self.user_a.email, "hacked-b@example.com")
        self.assertEqual(self.user_b.first_name, "Bob")
        self.assertEqual(self.user_b.email, "iso-b@example.com")
        self.assertEqual(self.user_b.phone_number, "9000000002")

    def test_04_customer_a_cannot_view_address_b_by_url_id(self):
        self._login(self.user_a)
        response = self.client.get(self.address_b_edit_url)
        self.assertEqual(response.status_code, 404)

        listing = self.client.get(self.address_list_url)
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "10 Alice Street")
        self.assertNotContains(listing, "99 Bob Secret Lane")
        self.assertNotContains(listing, "Bob Beta Secret")

    def test_05_customer_a_cannot_edit_deactivate_or_default_address_b(self):
        self._login(self.user_a)

        edit = self._post(
            self.address_b_edit_url,
            {
                "label": AddressLabel.HOME,
                "recipient_name": "Stolen",
                "phone_number": "9000000001",
                "line1": "Stolen Lane",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": "12.971600",
                "longitude": "77.594600",
                "delivery_instructions": "",
                "is_default": "on",
            },
            seed_url=self.address_list_url,
        )
        self.assertEqual(edit.status_code, 404)

        set_default = self._post(self.address_b_set_default_url, {})
        self.assertEqual(set_default.status_code, 404)

        deactivate = self._post(self.address_b_deactivate_url, {})
        self.assertEqual(deactivate.status_code, 404)

        self.address_b.refresh_from_db()
        self.address_b.address.refresh_from_db()
        self.assertEqual(self.address_b.recipient_name, "Bob Beta Secret")
        self.assertEqual(self.address_b.address.line1, "99 Bob Secret Lane")
        self.assertTrue(self.address_b.is_active)
        self.assertTrue(self.address_b.is_default)

    def test_06_customer_b_cannot_access_customer_a_addresses(self):
        self._login(self.user_b)

        listing = self.client.get(self.address_list_url)
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "99 Bob Secret Lane")
        self.assertNotContains(listing, "10 Alice Street")
        self.assertNotContains(listing, "Alice Alpha")

        self.assertEqual(self.client.get(self.address_a_edit_url).status_code, 404)
        self.assertEqual(self._post(self.address_a_set_default_url, {}).status_code, 404)
        self.assertEqual(self._post(self.address_a_deactivate_url, {}).status_code, 404)

        self.address_a.refresh_from_db()
        self.assertTrue(self.address_a.is_active)
        self.assertTrue(self.address_a.is_default)
        self.assertEqual(self.address_a.recipient_name, "Alice Alpha")

    def test_07_customer_cannot_submit_role_admin_or_is_staff(self):
        self._login(self.user_a)
        response = self._post(
            self.profile_edit_url,
            {
                "first_name": "Alice",
                "last_name": "Alpha",
                "email": "iso-a@example.com",
                "phone_number": "9000000001",
                "role": Role.ADMIN,
                "is_staff": "True",
                "is_superuser": "on",
            },
            seed_url=self.profile_edit_url,
        )
        self.assertEqual(response.status_code, 302)

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.role, Role.CUSTOMER)
        self.assertFalse(self.user_a.is_staff)
        self.assertFalse(self.user_a.is_superuser)

    def test_08_customer_cannot_change_verification_or_active_status(self):
        self._login(self.user_a)
        original_code = self.customer_a.customer_code
        response = self._post(
            self.profile_edit_url,
            {
                "first_name": "Alice",
                "last_name": "Alpha",
                "email": "iso-a@example.com",
                "phone_number": "9000000001",
                "verification_status": VerificationStatus.VERIFIED,
                "is_active": "off",
                "registration_source": RegistrationSource.MOBILE_APP,
                "customer_code": "CUHACKED01",
            },
            seed_url=self.profile_edit_url,
        )
        self.assertEqual(response.status_code, 302)

        self.user_a.refresh_from_db()
        self.customer_a.refresh_from_db()
        self.assertTrue(self.user_a.is_active)
        self.assertEqual(
            self.customer_a.verification_status,
            VerificationStatus.UNVERIFIED,
        )
        self.assertEqual(
            self.customer_a.registration_source,
            RegistrationSource.WEBSITE,
        )
        self.assertEqual(self.customer_a.customer_code, original_code)

    def test_09_inactive_customer_cannot_log_in(self):
        self.user_a.is_active = False
        self.user_a.save(update_fields=["is_active"])

        response = self._post(
            self.login_url,
            {"username": "iso-customer-a", "password": "secure-password-123"},
            seed_url=self.login_url,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        dashboard = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/customer/login/", dashboard.url)

    def test_10_anonymous_user_redirected_to_customer_login(self):
        for url in (
            self.dashboard_url,
            self.profile_url,
            self.profile_edit_url,
            self.address_list_url,
            self.address_a_edit_url,
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/customer/login/", response.url)

    def test_11_store_users_and_delivery_agents_cannot_access_customer_portal(self):
        for username in ("iso-store-user", "iso-delivery-agent"):
            with self.subTest(username=username):
                client = Client(enforce_csrf_checks=True)
                token = client.get(self.login_url).cookies["csrftoken"].value
                response = client.post(
                    self.login_url,
                    {
                        "username": username,
                        "password": "secure-password-123",
                        "csrfmiddlewaretoken": token,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Only Customers")
                self.assertNotIn("_auth_user_id", client.session)

                dashboard = client.get(self.dashboard_url)
                self.assertEqual(dashboard.status_code, 302)
                self.assertIn("/customer/login/", dashboard.url)

        # Even if already authenticated as store/delivery, protected pages deny access.
        self.client.force_login(self.store_user)
        self.assertEqual(self.client.get(self.dashboard_url).status_code, 403)
        self.client.force_login(self.delivery_agent)
        self.assertEqual(self.client.get(self.profile_url).status_code, 403)

    def test_12_unauthorized_address_requests_return_404(self):
        self._login(self.user_a)
        for url in (
            self.address_b_edit_url,
            self.address_b_set_default_url,
            self.address_b_deactivate_url,
        ):
            with self.subTest(url=url, method="GET"):
                if "edit" in url:
                    self.assertEqual(self.client.get(url).status_code, 404)
                else:
                    self.assertEqual(self.client.get(url).status_code, 405)

            with self.subTest(url=url, method="POST"):
                self.assertEqual(self._post(url, {}).status_code, 404)

        # Non-existent address ID also 404s for an authenticated customer.
        missing_edit = reverse(
            "customers:customer_portal_address_edit",
            kwargs={"pk": 999999},
        )
        self.assertEqual(self.client.get(missing_edit).status_code, 404)
