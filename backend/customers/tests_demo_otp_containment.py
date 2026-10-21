from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from .models import Customer, RegistrationSource, VerificationStatus
from .services import create_customer_with_user

User = get_user_model()


class DemoOTPContainmentTests(TestCase):
    routes = (
        "customer_otp_start",
        "customer_otp_verify",
        "customer_otp_resend",
        "customer_otp_profile",
    )
    password = "secure-password-123"
    legacy_code = "7391"
    unavailable = b"Mobile sign-in is unavailable. Please use password sign-in."

    @classmethod
    def setUpTestData(cls):
        cls.customer, cls.user = create_customer_with_user(
            user_data={
                "username": "containment-customer",
                "email": "containment@example.com",
                "first_name": "Test",
                "last_name": "Customer",
                "phone_number": "9000000081",
                "password": cls.password,
            },
            registration_source=RegistrationSource.WEBSITE,
        )


    def payload(self, *, phone_number=None):
        return {
            "phone_number": phone_number or self.user.phone_number,
            "otp_code": self.legacy_code,
            "first_name": "Unverified",
            "last_name": "Signup",
            "email": "unverified@example.com",
            "verified": "true",
        }

    def accounts_snapshot(self):
        return (
            list(User.objects.order_by("pk").values()),
            list(Customer.objects.order_by("pk").values()),
        )

    def assert_disabled(self, client, route, *, method="post", payload=None):
        accounts_before = self.accounts_snapshot()
        session_before = dict(client.session)
        session_key_before = client.session.session_key
        url = reverse(f"customers:{route}")
        if method == "post":
            response = client.post(
                url,
                self.payload() if payload is None else payload,
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            )
        else:
            response = client.get(url)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.content, self.unavailable)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        for directive in ("no-cache", "no-store", "must-revalidate", "max-age=0"):
            self.assertIn(directive, response["Cache-Control"])
        self.assertIn("Expires", response)
        self.assertNotIn(self.legacy_code, response.content.decode())
        self.assertNotIn(self.legacy_code, str(dict(response.items())))
        self.assertNotIn("messages", response.cookies)
        self.assertEqual(list(get_messages(response.wsgi_request)), [])
        self.assertEqual(self.accounts_snapshot(), accounts_before)
        self.assertEqual(dict(client.session), session_before)
        self.assertEqual(client.session.session_key, session_key_before)
        return response











