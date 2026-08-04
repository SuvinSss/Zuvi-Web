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
        self.url = reverse("customers:customer_register")
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

    def _post(self, payload):
        get_response = self.client.get(self.url)
        token = get_response.cookies["csrftoken"].value
        data = dict(payload)
        data["csrfmiddlewaretoken"] = token
        return self.client.post(self.url, data)

    def test_get_register_page_includes_csrf(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Create your account")

    def test_successful_registration(self):
        response = self._post(self.valid_payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, settings.CUSTOMER_LOGIN_URL)

        user = User.objects.get(username="ada-customer")
        self.assertEqual(user.email, "ada@example.com")
        self.assertEqual(user.phone_number, "9876543210")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("secure-password-123"))
        self.assertNotEqual(user.password, "secure-password-123")

        customer = Customer.objects.get(user=user)
        self.assertEqual(customer.registration_source, RegistrationSource.WEBSITE)
        self.assertIsNone(customer.created_by)
        self.assertEqual(customer.verification_status, VerificationStatus.UNVERIFIED)
        self.assertFalse(CustomerAddress.objects.filter(customer=customer).exists())

    def test_password_mismatch_rejected(self):
        payload = dict(self.valid_payload)
        payload["confirm_password"] = "different-password-123"
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="ada-customer").exists())
        self.assertFormError(
            response.context["form"],
            "confirm_password",
            "Passwords do not match.",
        )

    def test_terms_required(self):
        payload = dict(self.valid_payload)
        payload.pop("accept_terms")
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="ada-customer").exists())
        self.assertTrue(response.context["form"].errors.get("accept_terms"))

    def test_duplicate_username_email_phone_rejected(self):
        self._post(self.valid_payload)
        duplicate = {
            "first_name": "Other",
            "last_name": "User",
            "username": "ada-customer",
            "email": "other@example.com",
            "phone_number": "9000000001",
            "password": "secure-password-123",
            "confirm_password": "secure-password-123",
            "accept_terms": "on",
        }
        response = self._post(duplicate)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "username",
            "This username is already in use.",
        )

        duplicate["username"] = "other-user"
        duplicate["email"] = "ada@example.com"
        response = self._post(duplicate)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "email",
            "This email is already in use.",
        )

        duplicate["email"] = "other@example.com"
        duplicate["phone_number"] = "9876543210"
        response = self._post(duplicate)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "phone_number",
            "This phone number is already in use.",
        )
        self.assertEqual(User.objects.filter(role=Role.CUSTOMER).count(), 1)

    def test_weak_password_rejected(self):
        payload = dict(self.valid_payload)
        payload["password"] = "123"
        payload["confirm_password"] = "123"
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="ada-customer").exists())
        self.assertTrue(response.context["form"].errors.get("password"))

    def test_privilege_fields_in_post_are_ignored(self):
        payload = dict(self.valid_payload)
        payload.update(
            {
                "role": Role.SUPER_ADMIN,
                "is_staff": "True",
                "is_superuser": "on",
                "is_verified": "on",
                "verification_status": VerificationStatus.VERIFIED,
                "created_by": "1",
                "registration_source": RegistrationSource.MANAGEMENT_PORTAL,
            }
        )
        response = self._post(payload)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username="ada-customer")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

        customer = user.customer_profile
        self.assertEqual(customer.registration_source, RegistrationSource.WEBSITE)
        self.assertEqual(customer.verification_status, VerificationStatus.UNVERIFIED)
        self.assertIsNone(customer.created_by)

    def test_csrf_required(self):
        response = self.client.post(self.url, self.valid_payload)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="ada-customer").exists())

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
