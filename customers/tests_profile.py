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
        self.profile_url = reverse("customers:customer_portal_profile")
        self.edit_url = reverse("customers:customer_portal_profile_edit")

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

    def _login(self, user):
        self.client.force_login(user)
        # Seed CSRF cookie after force_login for enforce_csrf_checks posts.
        self.client.get(self.profile_url)

    def _post_edit(self, payload):
        token = self._csrf_token(self.edit_url)
        data = dict(payload)
        data["csrfmiddlewaretoken"] = token
        return self.client.post(self.edit_url, data)

    def test_profile_page_shows_own_editable_and_readonly_fields(self):
        self._login(self.user_a)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Alpha")
        self.assertContains(response, "profile-a@example.com")
        self.assertContains(response, "9111111111")
        self.assertContains(response, "profile-customer-a")
        self.assertContains(response, self.customer_a.customer_code)
        self.assertContains(response, "Website")
        self.assertContains(response, "Unverified")
        self.assertContains(response, "Active")
        self.assertContains(response, "Customer")
        self.assertContains(response, "Self-registered")
        self.assertContains(response, "Edit profile")
        self.assertNotContains(response, self.customer_b.customer_code)
        self.assertNotContains(response, "profile-b@example.com")

    def test_edit_page_includes_csrf_and_readonly_account_fields(self):
        self._login(self.user_a)
        response = self.client.get(self.edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, self.customer_a.customer_code)
        self.assertContains(response, "profile-customer-a")
        self.assertContains(response, "Website")
        self.assertContains(response, "Unverified")
        self.assertNotContains(response, 'name="username"')
        self.assertNotContains(response, 'name="role"')
        self.assertNotContains(response, 'name="is_staff"')
        self.assertNotContains(response, 'name="is_superuser"')
        self.assertNotContains(response, 'name="customer_id"')

    def test_successful_profile_update(self):
        self._login(self.user_a)
        response = self._post_edit(
            {
                "first_name": "Alicia",
                "last_name": "Updated",
                "email": "alicia-updated@example.com",
                "phone_number": "9333333333",
            }
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.profile_url)

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.first_name, "Alicia")
        self.assertEqual(self.user_a.last_name, "Updated")
        self.assertEqual(self.user_a.email, "alicia-updated@example.com")
        self.assertEqual(self.user_a.phone_number, "9333333333")
        self.assertEqual(self.user_a.username, "profile-customer-a")
        self.assertEqual(self.user_a.role, Role.CUSTOMER)
        self.assertFalse(self.user_a.is_staff)
        self.assertFalse(self.user_a.is_superuser)
        self.assertTrue(self.user_a.is_active)

        profile = self.client.get(self.profile_url)
        self.assertContains(profile, "Alicia")
        self.assertContains(profile, "alicia-updated@example.com")

    def test_privilege_escalation_fields_in_post_are_ignored(self):
        original_code = self.customer_a.customer_code
        original_created = self.customer_a.created_at
        self._login(self.user_a)
        response = self._post_edit(
            {
                "first_name": "Alice",
                "last_name": "Alpha",
                "email": "profile-a@example.com",
                "phone_number": "9111111111",
                "username": "hacked-username",
                "role": Role.SUPER_ADMIN,
                "is_staff": "on",
                "is_superuser": "on",
                "is_active": "off",
                "verification_status": VerificationStatus.VERIFIED,
                "registration_source": RegistrationSource.MOBILE_APP,
                "customer_code": "CUHACKED01",
                "customer_id": self.customer_b.pk,
                "created_by": self.user_b.pk,
            }
        )
        self.assertEqual(response.status_code, 302)

        self.user_a.refresh_from_db()
        self.customer_a.refresh_from_db()
        self.assertEqual(self.user_a.username, "profile-customer-a")
        self.assertEqual(self.user_a.role, Role.CUSTOMER)
        self.assertFalse(self.user_a.is_staff)
        self.assertFalse(self.user_a.is_superuser)
        self.assertTrue(self.user_a.is_active)
        self.assertEqual(self.customer_a.customer_code, original_code)
        self.assertEqual(
            self.customer_a.verification_status,
            VerificationStatus.UNVERIFIED,
        )
        self.assertEqual(
            self.customer_a.registration_source,
            RegistrationSource.WEBSITE,
        )
        self.assertIsNone(self.customer_a.created_by_id)
        self.assertEqual(self.customer_a.created_at, original_created)

    def test_customer_id_in_post_cannot_edit_another_customer(self):
        self._login(self.user_a)
        response = self._post_edit(
            {
                "customer_id": self.customer_b.pk,
                "first_name": "ShouldNotApply",
                "last_name": "ToBob",
                "email": "should-not-apply-to-b@example.com",
                "phone_number": "9444444444",
            }
        )
        self.assertEqual(response.status_code, 302)

        self.user_a.refresh_from_db()
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_a.first_name, "ShouldNotApply")
        self.assertEqual(self.user_a.email, "should-not-apply-to-b@example.com")
        self.assertEqual(self.user_b.first_name, "Bob")
        self.assertEqual(self.user_b.email, "profile-b@example.com")
        self.assertEqual(self.user_b.phone_number, "9222222222")

    def test_profile_isolation_between_customers(self):
        self._login(self.user_a)
        response_a = self.client.get(self.profile_url)
        self.assertContains(response_a, self.customer_a.customer_code)
        self.assertNotContains(response_a, self.customer_b.customer_code)
        self.assertNotContains(response_a, "Bob")
        self.assertNotContains(response_a, "profile-b@example.com")

        response_a_edit = self.client.get(
            self.edit_url,
            {"customer_id": self.customer_b.pk},
        )
        self.assertEqual(response_a_edit.status_code, 200)
        self.assertEqual(response_a_edit.context["customer"].pk, self.customer_a.pk)
        self.assertContains(response_a_edit, self.customer_a.customer_code)
        self.assertNotContains(response_a_edit, self.customer_b.customer_code)

        self._login(self.user_b)
        response_b = self.client.get(self.profile_url)
        self.assertContains(response_b, self.customer_b.customer_code)
        self.assertContains(response_b, "Verified")
        self.assertContains(response_b, "profile-admin-creator")
        self.assertNotContains(response_b, self.customer_a.customer_code)
        self.assertNotContains(response_b, "Alice")

    def test_duplicate_email_rejected(self):
        self._login(self.user_a)
        response = self._post_edit(
            {
                "first_name": "Alice",
                "last_name": "Alpha",
                "email": "profile-b@example.com",
                "phone_number": "9111111111",
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "email",
            "This email is already in use.",
        )
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.email, "profile-a@example.com")

    def test_duplicate_phone_rejected(self):
        self._login(self.user_a)
        response = self._post_edit(
            {
                "first_name": "Alice",
                "last_name": "Alpha",
                "email": "profile-a@example.com",
                "phone_number": "9222222222",
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "phone_number",
            "This phone number is already in use.",
        )
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.phone_number, "9111111111")

    def test_edit_rejects_missing_csrf(self):
        plain = Client(enforce_csrf_checks=True)
        plain.force_login(self.user_a)
        plain.get(self.edit_url)
        response = plain.post(
            self.edit_url,
            {
                "first_name": "No",
                "last_name": "Token",
                "email": "notoken@example.com",
                "phone_number": "9555555555",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.email, "profile-a@example.com")

    def test_anonymous_redirected_to_customer_login(self):
        for url in (self.profile_url, self.edit_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/customer/login/", response.url)

    def test_same_email_and_phone_allowed_for_own_account(self):
        self._login(self.user_a)
        response = self._post_edit(
            {
                "first_name": "Alice",
                "last_name": "Renamed",
                "email": "profile-a@example.com",
                "phone_number": "9111111111",
            }
        )
        self.assertEqual(response.status_code, 302)
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.last_name, "Renamed")
