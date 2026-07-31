from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import AdminAuditLog, Role

from .models import AddressLabel, Customer, RegistrationSource, VerificationStatus
from .services import create_customer_delivery_address, create_customer_with_user
from .tests_permissions import CustomerPermissionTestMixin

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CustomerManagementFeatureTests(CustomerPermissionTestMixin, TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.super_admin = self.create_super_admin(username="mgmt-super")
        self.admin = self.create_admin(username="mgmt-admin")
        self.grant_customer_perms(
            self.admin,
            "view_customer",
            "add_customer",
            "change_customer",
            "activate_customer",
            "verify_customer",
        )
        self.list_url = reverse("customers:customer_list")
        self.create_url = reverse("customers:customer_create")

    def _login_admin(self):
        self.client.force_login(self.admin)
        self.client.get(self.list_url)

    def _csrf(self, url):
        return self.client.get(url).cookies["csrftoken"].value

    def _create_payload(self, **overrides):
        payload = {
            "first_name": "Casey",
            "last_name": "Customer",
            "username": "casey-mgmt",
            "email": "casey-mgmt@example.com",
            "phone_number": "9333333333",
            "password": "secure-password-123",
            "confirm_password": "secure-password-123",
            "notes": "Created from management portal",
            "address_label": "",
            "address_recipient_name": "",
            "address_phone_number": "",
            "address_line1": "",
            "address_line2": "",
            "address_landmark": "",
            "address_city": "",
            "address_district": "",
            "address_state": "",
            "address_postal_code": "",
            "address_latitude": "",
            "address_longitude": "",
            "address_delivery_instructions": "",
        }
        payload.update(overrides)
        return payload

    def test_create_customer_sets_role_source_created_by_and_audit(self):
        self._login_admin()
        token = self._csrf(self.create_url)
        payload = self._create_payload()
        payload["csrfmiddlewaretoken"] = token
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, 302)

        customer = Customer.objects.get(user__username="casey-mgmt")
        user = customer.user
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(customer.registration_source, RegistrationSource.MANAGEMENT_PORTAL)
        self.assertEqual(customer.created_by_id, self.admin.pk)
        self.assertTrue(user.check_password("secure-password-123"))
        self.assertNotEqual(user.password, "secure-password-123")

        detail = self.client.get(
            reverse("customers:customer_detail", kwargs={"pk": customer.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "secure-password-123")
        self.assertNotContains(detail, user.password)

        audit = AdminAuditLog.objects.filter(
            action=AdminAuditLog.Action.CUSTOMER_CREATED,
            target_user=user,
        ).latest("created_at")
        self.assertEqual(audit.actor_id, self.admin.pk)
        self.assertNotIn("password", str(audit.metadata).lower())
        self.assertNotIn("secure-password-123", audit.description)
        self.assertNotIn("secure-password-123", str(audit.metadata))

    def test_audit_ip_ignores_spoofed_x_forwarded_for(self):
        self._login_admin()
        token = self._csrf(self.create_url)
        payload = self._create_payload(
            username="ip-spoof-customer",
            email="ip-spoof-customer@example.com",
            phone_number="9333333399",
        )
        payload["csrfmiddlewaretoken"] = token
        response = self.client.post(
            self.create_url,
            payload,
            HTTP_X_FORWARDED_FOR="203.0.113.50, 198.51.100.1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username="ip-spoof-customer")
        audit = AdminAuditLog.objects.filter(
            action=AdminAuditLog.Action.CUSTOMER_CREATED,
            target_user=user,
        ).latest("created_at")
        self.assertEqual(audit.ip_address, "127.0.0.1")
        self.assertNotEqual(audit.ip_address, "203.0.113.50")

    def test_create_with_optional_first_address(self):
        self._login_admin()
        token = self._csrf(self.create_url)
        payload = self._create_payload(
            username="casey-with-addr",
            email="casey-with-addr@example.com",
            phone_number="9444444444",
            address_label=AddressLabel.HOME,
            address_recipient_name="Casey Customer",
            address_phone_number="9444444444",
            address_line1="12 Admin Street",
            address_city="Bengaluru",
            address_state="Karnataka",
            address_postal_code="560001",
            address_latitude="12.971600",
            address_longitude="77.594600",
            address_delivery_instructions="Leave at gate",
        )
        payload["csrfmiddlewaretoken"] = token
        response = self.client.post(self.create_url, payload)
        self.assertEqual(response.status_code, 302)

        customer = Customer.objects.get(user__username="casey-with-addr")
        address = customer.addresses.get()
        self.assertTrue(address.is_default)
        self.assertTrue(address.is_active)
        self.assertEqual(address.address.line1, "12 Admin Street")
        self.assertEqual(address.delivery_instructions, "Leave at gate")

    def test_list_shows_required_columns_search_filters_and_address_count(self):
        customer, user = create_customer_with_user(
            user_data={
                "username": "list-customer",
                "email": "list-customer@example.com",
                "first_name": "List",
                "last_name": "Person",
                "phone_number": "9555555555",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        create_customer_delivery_address(
            customer=customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "List Person",
                "phone_number": "9555555555",
                "line1": "1 List Road",
                "line2": "",
                "landmark": "",
                "city": "Bengaluru",
                "district": "",
                "state": "Karnataka",
                "postal_code": "560001",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "",
                "is_default": True,
            },
        )
        self._login_admin()
        response = self.client.get(self.list_url)
        self.assertContains(response, customer.customer_code)
        self.assertContains(response, "List Person")
        self.assertContains(response, "list-customer")
        self.assertContains(response, "list-customer@example.com")
        self.assertContains(response, "9555555555")
        self.assertContains(response, "Website")
        self.assertContains(response, "Unverified")
        matched = next(c for c in response.context["page_obj"] if c.pk == customer.pk)
        self.assertEqual(matched.saved_address_count, 1)

        searched = self.client.get(self.list_url, {"q": "List"})
        self.assertContains(searched, customer.customer_code)

        filtered = self.client.get(
            self.list_url,
            {"registration_source": RegistrationSource.WEBSITE, "is_active": "true"},
        )
        self.assertContains(filtered, customer.customer_code)

        filtered_out = self.client.get(
            self.list_url,
            {"registration_source": RegistrationSource.MOBILE_APP},
        )
        self.assertNotContains(filtered_out, customer.customer_code)

    def test_edit_ignores_privilege_and_password_fields(self):
        customer, user = create_customer_with_user(
            user_data={
                "username": "edit-customer",
                "email": "edit-customer@example.com",
                "first_name": "Edit",
                "last_name": "Me",
                "phone_number": "9666666666",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        original_password = user.password
        edit_url = reverse("customers:customer_edit", kwargs={"pk": customer.pk})
        self._login_admin()
        token = self._csrf(edit_url)
        response = self.client.post(
            edit_url,
            {
                "csrfmiddlewaretoken": token,
                "first_name": "Edited",
                "last_name": "Customer",
                "email": "edited-customer@example.com",
                "phone_number": "9666666666",
                "notes": "Updated notes",
                "role": Role.ADMIN,
                "is_staff": "on",
                "is_superuser": "on",
                "is_active": "off",
                "username": "hacked",
                "password": "new-password-should-ignore",
                "verification_status": VerificationStatus.VERIFIED,
                "registration_source": RegistrationSource.MOBILE_APP,
            },
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        customer.refresh_from_db()
        self.assertEqual(user.first_name, "Edited")
        self.assertEqual(user.email, "edited-customer@example.com")
        self.assertEqual(user.username, "edit-customer")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertEqual(user.password, original_password)
        self.assertEqual(customer.verification_status, VerificationStatus.UNVERIFIED)
        self.assertEqual(customer.registration_source, RegistrationSource.WEBSITE)
        self.assertEqual(customer.notes, "Updated notes")

        audit = AdminAuditLog.objects.filter(
            action=AdminAuditLog.Action.CUSTOMER_UPDATED,
            target_user=user,
        ).latest("created_at")
        self.assertEqual(audit.actor_id, self.admin.pk)

    def test_create_rejects_missing_csrf(self):
        self.client.force_login(self.admin)
        self.client.get(self.create_url)
        response = self.client.post(self.create_url, self._create_payload())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Customer.objects.filter(user__username="casey-mgmt").exists())

    def test_edit_page_does_not_expose_password_hash(self):
        customer, user = create_customer_with_user(
            user_data={
                "username": "hash-customer",
                "email": "hash-customer@example.com",
                "first_name": "Hash",
                "last_name": "Check",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self._login_admin()
        response = self.client.get(
            reverse("customers:customer_edit", kwargs={"pk": customer.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, user.password)
        self.assertNotContains(response, 'name="password"')
        self.assertNotContains(response, 'name="role"')
