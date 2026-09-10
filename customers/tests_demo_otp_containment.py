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

    def make_client(self, *, otp_session=None, authenticated=False):
        client = Client(enforce_csrf_checks=True)
        if authenticated:
            client.force_login(self.user)
        if otp_session is not None:
            session = client.session
            session["customer_otp"] = otp_session
            session.save()
        client.get(reverse("customers:customer_portal_login"))
        # An authenticated login request redirects, so use the registration
        # page to obtain CSRF credentials in that case.
        if "csrftoken" not in client.cookies:
            client.get(reverse("customers:customer_register"))
        return client

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

    def test_direct_get_routes_disabled_with_debug_on_and_off(self):
        for debug in (True, False):
            with self.settings(DEBUG=debug):
                for route in self.routes:
                    with self.subTest(debug=debug, route=route):
                        client = self.make_client()
                        self.assert_disabled(client, route, method="get")
                        self.assertNotIn("_auth_user_id", client.session)

    def test_valid_csrf_posts_reach_disabled_routes_with_debug_on_and_off(self):
        for debug in (True, False):
            with self.settings(DEBUG=debug):
                for route in self.routes:
                    with self.subTest(debug=debug, route=route):
                        client = self.make_client()
                        self.assert_disabled(client, route)
                        self.assertNotIn("customer_otp", client.session)
                        self.assertNotIn("_auth_user_id", client.session)

    def test_missing_or_invalid_csrf_posts_remain_forbidden(self):
        for debug in (True, False):
            with self.settings(DEBUG=debug):
                for route in self.routes:
                    for credentials in ("none", "cookie_only", "incorrect_token"):
                        with self.subTest(debug=debug, route=route, csrf=credentials):
                            client = (
                                Client(enforce_csrf_checks=True)
                                if credentials == "none"
                                else self.make_client()
                            )
                            headers = {}
                            if credentials == "incorrect_token":
                                token = client.cookies["csrftoken"].value
                                headers["HTTP_X_CSRFTOKEN"] = (
                                    ("a" if token[0] != "a" else "b") + token[1:]
                                )
                            before = self.accounts_snapshot()
                            response = client.post(
                                reverse(f"customers:{route}"), self.payload(), **headers
                            )
                            self.assertEqual(response.status_code, 403)
                            self.assertNotIn(self.legacy_code, response.content.decode())
                            self.assertNotIn("_auth_user_id", client.session)
                            self.assertEqual(self.accounts_snapshot(), before)

    def test_matching_legacy_session_code_cannot_authenticate(self):
        for route in self.routes:
            with self.subTest(route=route):
                client = self.make_client(otp_session={
                    "phone_number": self.user.phone_number,
                    "code": self.legacy_code,
                })
                self.assert_disabled(client, route)
                self.assertNotIn("_auth_user_id", client.session)

    def test_signup_completion_rejects_missing_unverified_and_forged_sessions(self):
        legacy = {"phone_number": "9000000099", "code": self.legacy_code}
        states = (None, {}, legacy, {**legacy, "verified": True, "otp_verified": True})
        for state in states:
            with self.subTest(session=state):
                client = self.make_client(otp_session=state)
                self.assert_disabled(
                    client, "customer_otp_profile",
                    payload=self.payload(phone_number=legacy["phone_number"]),
                )
                self.assertNotIn("_auth_user_id", client.session)

    def test_inactive_customer_is_not_activated_or_verified(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        for route in self.routes:
            with self.subTest(route=route):
                client = self.make_client(otp_session={
                    "phone_number": self.user.phone_number,
                    "code": self.legacy_code,
                    "verified": True,
                })
                self.assert_disabled(client, route)
                self.assertNotIn("_auth_user_id", client.session)

    def test_unusable_password_customer_cannot_authenticate_via_demo(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        for route in self.routes:
            with self.subTest(route=route):
                client = self.make_client(otp_session={
                    "phone_number": self.user.phone_number,
                    "code": self.legacy_code,
                })
                self.assert_disabled(client, route)
                self.assertNotIn("_auth_user_id", client.session)

    def test_existing_authenticated_session_survives_all_disabled_routes(self):
        client = self.make_client(authenticated=True, otp_session={
            "phone_number": self.user.phone_number, "code": self.legacy_code,
        })
        for route in self.routes:
            for method in ("get", "post"):
                with self.subTest(route=route, method=method):
                    self.assert_disabled(client, route, method=method)
                    self.assertEqual(client.session["_auth_user_id"], str(self.user.pk))

    def test_account_existence_does_not_change_disabled_response(self):
        for route in self.routes:
            responses = []
            for phone in (self.user.phone_number, "9000000099"):
                with self.subTest(route=route, phone=phone):
                    client = self.make_client(otp_session={
                        "phone_number": phone, "code": self.legacy_code,
                    })
                    responses.append(self.assert_disabled(
                        client, route, payload=self.payload(phone_number=phone),
                    ).content)
            self.assertEqual(responses[0], responses[1])

    def test_password_login_still_works_after_disabled_demo_attempt(self):
        client = self.make_client()
        self.assert_disabled(client, "customer_otp_start")
        response = client.post(
            reverse("customers:customer_portal_login"),
            {"username": self.user.username, "password": self.password},
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertRedirects(response, reverse("customers:customer_portal_dashboard"))
        self.assertEqual(client.session["_auth_user_id"], str(self.user.pk))

    def test_password_registration_and_subsequent_login_still_work(self):
        client = self.make_client()
        response = client.post(
            reverse("customers:customer_register"),
            {
                "username": "password-signup",
                "email": "password-signup@example.com",
                "phone_number": "9000000098",
                "first_name": "Password",
                "last_name": "Signup",
                "password": self.password,
                "confirm_password": self.password,
                "accept_terms": "on",
            },
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertRedirects(response, reverse("customers:customer_portal_login"))
        user = User.objects.get(username="password-signup")
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.customer_profile.verification_status, VerificationStatus.UNVERIFIED)
        self.assertNotIn("_auth_user_id", client.session)
        response = client.post(
            reverse("customers:customer_portal_login"),
            {"username": user.username, "password": self.password},
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertRedirects(response, reverse("customers:customer_portal_dashboard"))
        self.assertEqual(client.session["_auth_user_id"], str(user.pk))
