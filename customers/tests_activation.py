from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import AdminAuditLog, Role

from .models import AddressLabel, Customer, CustomerAddress, RegistrationSource, VerificationStatus
from .services import (
    create_customer_delivery_address,
    create_customer_with_user,
    set_customer_active,
)
from .tests_permissions import CustomerPermissionTestMixin

User = get_user_model()


class CustomerActivationVerificationTests(CustomerPermissionTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.super_admin = self.create_super_admin(username="act-super")
        self.admin = self.create_admin(username="act-admin")
        self.customer, self.user = create_customer_with_user(
            user_data={
                "username": "act-customer",
                "email": "act-customer@example.com",
                "first_name": "Act",
                "last_name": "Customer",
                "phone_number": "9777777777",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        self.address = create_customer_delivery_address(
            customer=self.customer,
            data={
                "label": AddressLabel.HOME,
                "recipient_name": "Act Customer",
                "phone_number": "9777777777",
                "line1": "77 Preserve Lane",
                "line2": "Suite 1",
                "landmark": "Park",
                "city": "Bengaluru",
                "district": "Bengaluru Urban",
                "state": "Karnataka",
                "postal_code": "560077",
                "latitude": Decimal("12.971600"),
                "longitude": Decimal("77.594600"),
                "delivery_instructions": "Keep parcel",
                "is_default": True,
            },
        )
        self.detail_url = reverse(
            "customers:customer_detail",
            kwargs={"pk": self.customer.pk},
        )
        self.toggle_url = reverse(
            "customers:customer_toggle_status",
            kwargs={"pk": self.customer.pk},
        )
        self.verify_url = reverse(
            "customers:customer_verify",
            kwargs={"pk": self.customer.pk},
        )
        self.login_url = reverse("customers:customer_portal_login")
        self.dashboard_url = reverse("customers:customer_portal_dashboard")

    def test_deactivation_requires_reason(self):
        self.client.login(username="act-super", password="secure-password-123")
        response = self.client.post(self.toggle_url, {})
        self.assertEqual(response.status_code, 302)
        self.customer.user.refresh_from_db()
        self.assertTrue(self.customer.user.is_active)
        self.assertFalse(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.CUSTOMER_DEACTIVATED,
                target_user=self.user,
            ).exists()
        )

        with self.assertRaises(ValidationError):
            set_customer_active(
                customer=self.customer,
                is_active=False,
                actor=self.super_admin,
                reason="",
            )

    def test_deactivate_and_reactivate_preserves_data_and_records_audit(self):
        self.client.login(username="act-super", password="secure-password-123")
        user_id = self.user.pk
        customer_id = self.customer.pk
        address_id = self.address.pk
        location_id = self.address.address_id
        original_code = self.customer.customer_code
        original_line1 = self.address.address.line1

        response = self.client.post(
            self.toggle_url,
            {"reason": "Fraud review"},
        )
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.address.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(User.objects.filter(pk=user_id).exists())
        self.assertTrue(Customer.objects.filter(pk=customer_id).exists())
        self.assertTrue(CustomerAddress.objects.filter(pk=address_id).exists())
        self.assertEqual(self.customer.customer_code, original_code)
        self.assertEqual(self.address.address_id, location_id)
        self.assertEqual(self.address.address.line1, original_line1)
        self.assertEqual(self.address.recipient_name, "Act Customer")
        self.assertTrue(self.address.is_default)

        audit = AdminAuditLog.objects.filter(
            action=AdminAuditLog.Action.CUSTOMER_DEACTIVATED,
            target_user=self.user,
        ).latest("created_at")
        self.assertEqual(audit.actor_id, self.super_admin.pk)
        self.assertEqual(audit.metadata.get("reason"), "Fraud review")
        self.assertIn("Fraud review", audit.description)

        reactivate = self.client.post(self.toggle_url)
        self.assertEqual(reactivate.status_code, 302)
        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.address.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.customer.customer_code, original_code)
        self.assertEqual(self.address.address.line1, original_line1)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.CUSTOMER_ACTIVATED,
                target_user=self.user,
            ).exists()
        )

    def test_deactivated_customer_cannot_login_to_customer_portal(self):
        set_customer_active(
            customer=self.customer,
            is_active=False,
            actor=self.super_admin,
            reason="Temporary hold",
        )
        response = self.client.post(
            self.login_url,
            {"username": "act-customer", "password": "secure-password-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        dashboard = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/customer/login/", dashboard.url)

    def test_reactivated_customer_can_login_again(self):
        set_customer_active(
            customer=self.customer,
            is_active=False,
            actor=self.super_admin,
            reason="Temporary hold",
        )
        set_customer_active(
            customer=self.customer,
            is_active=True,
            actor=self.super_admin,
        )
        response = self.client.post(
            self.login_url,
            {"username": "act-customer", "password": "secure-password-123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard_url)
        self.assertIn("_auth_user_id", self.client.session)

    def test_admin_without_activate_permission_cannot_deactivate(self):
        self.grant_customer_perms(self.admin, "view_customer")
        self.client.login(username="act-admin", password="secure-password-123")
        response = self.client.post(
            self.toggle_url,
            {"reason": "Should fail"},
        )
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_admin_with_activate_permission_can_deactivate(self):
        self.grant_customer_perms(self.admin, "view_customer", "activate_customer")
        self.client.login(username="act-admin", password="secure-password-123")
        response = self.client.post(
            self.toggle_url,
            {"reason": "Admin approved deactivation"},
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_admin_without_verify_permission_cannot_verify(self):
        self.grant_customer_perms(self.admin, "view_customer", "change_customer")
        self.client.login(username="act-admin", password="secure-password-123")
        response = self.client.post(
            self.verify_url,
            {"verification_status": VerificationStatus.VERIFIED},
        )
        self.assertEqual(response.status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.verification_status,
            VerificationStatus.UNVERIFIED,
        )

    def test_admin_with_verify_permission_can_verify_and_audit(self):
        self.grant_customer_perms(self.admin, "view_customer", "verify_customer")
        self.client.login(username="act-admin", password="secure-password-123")
        response = self.client.post(
            self.verify_url,
            {"verification_status": VerificationStatus.VERIFIED},
        )
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.verification_status,
            VerificationStatus.VERIFIED,
        )
        audit = AdminAuditLog.objects.filter(
            action=AdminAuditLog.Action.CUSTOMER_VERIFIED,
            target_user=self.user,
        ).latest("created_at")
        self.assertEqual(audit.actor_id, self.admin.pk)

    def test_status_and_verification_require_post(self):
        self.client.login(username="act-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)
        self.assertEqual(self.client.get(self.verify_url).status_code, 405)

    def test_detail_page_shows_deactivation_reason_field_for_active_customer(self):
        self.grant_customer_perms(self.admin, "view_customer", "activate_customer")
        self.client.login(username="act-admin", password="secure-password-123")
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reason for deactivation")
        self.assertContains(response, "name=\"reason\"")
