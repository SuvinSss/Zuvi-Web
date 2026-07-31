from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role

from .decorators import user_has_customer_permission
from .models import Customer, RegistrationSource, VerificationStatus
from .services import create_customer_with_user

User = get_user_model()


class CustomerPermissionTestMixin:
    def create_super_admin(self, username="cust-super"):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def create_admin(self, username="cust-admin"):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
        )

    def create_customer_account(self, username="end-customer"):
        customer, user = create_customer_with_user(
            user_data={
                "username": username,
                "email": f"{username}@example.com",
                "first_name": "End",
                "last_name": "Customer",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        return customer, user

    def grant_customer_perms(self, user, *codenames):
        for codename in codenames:
            permission = Permission.objects.get(
                content_type__app_label="customers",
                codename=codename,
            )
            user.user_permissions.add(permission)
        return User.objects.get(pk=user.pk)

    def _perm(self, codename):
        return Permission.objects.get(
            content_type__app_label="customers",
            codename=codename,
        )


class CustomerPermissionHelperTests(CustomerPermissionTestMixin, TestCase):
    def setUp(self):
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()
        self.customer_profile, self.customer_user = self.create_customer_account()

    def test_custom_permissions_exist(self):
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="customers",
                codename="activate_customer",
            ).exists()
        )
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="customers",
                codename="verify_customer",
            ).exists()
        )
        for codename in ("view_customer", "add_customer", "change_customer"):
            self.assertTrue(
                Permission.objects.filter(
                    content_type__app_label="customers",
                    codename=codename,
                ).exists()
            )

    def test_super_admin_has_all_customer_permissions(self):
        for perm in (
            "customers.view_customer",
            "customers.add_customer",
            "customers.change_customer",
            "customers.activate_customer",
            "customers.verify_customer",
        ):
            self.assertTrue(user_has_customer_permission(self.super_admin, perm))

    def test_admin_without_permissions_denied(self):
        for perm in (
            "customers.view_customer",
            "customers.add_customer",
            "customers.change_customer",
            "customers.activate_customer",
            "customers.verify_customer",
        ):
            self.assertFalse(user_has_customer_permission(self.admin, perm))

    def test_admin_with_granted_permission(self):
        self.grant_customer_perms(self.admin, "view_customer")
        self.admin = User.objects.get(pk=self.admin.pk)
        self.assertTrue(
            user_has_customer_permission(self.admin, "customers.view_customer")
        )
        self.assertFalse(
            user_has_customer_permission(self.admin, "customers.add_customer")
        )

    def test_customer_never_has_management_permission_helper(self):
        self.grant_customer_perms(
            self.customer_user,
            "view_customer",
            "add_customer",
            "change_customer",
            "activate_customer",
            "verify_customer",
        )
        self.customer_user = User.objects.get(pk=self.customer_user.pk)
        for perm in (
            "customers.view_customer",
            "customers.add_customer",
            "customers.change_customer",
            "customers.activate_customer",
            "customers.verify_customer",
        ):
            self.assertFalse(
                user_has_customer_permission(self.customer_user, perm),
                msg=f"Customer must not pass management check for {perm}",
            )


class CustomerManagementPermissionViewTests(CustomerPermissionTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()
        self.customer, self.customer_user = self.create_customer_account(
            username="managed-customer"
        )
        self.list_url = reverse("customers:customer_list")
        self.create_url = reverse("customers:customer_create")
        self.detail_url = reverse(
            "customers:customer_detail", kwargs={"pk": self.customer.pk}
        )
        self.edit_url = reverse(
            "customers:customer_edit", kwargs={"pk": self.customer.pk}
        )
        self.toggle_url = reverse(
            "customers:customer_toggle_status", kwargs={"pk": self.customer.pk}
        )
        self.verify_url = reverse(
            "customers:customer_verify", kwargs={"pk": self.customer.pk}
        )

    def _login_admin_with(self, *codenames):
        self.grant_customer_perms(self.admin, *codenames)
        self.client.login(username="cust-admin", password="secure-password-123")

    def test_super_admin_bypasses_customer_permission_checks(self):
        self.client.login(username="cust-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.create_url).status_code, 200)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)

        toggle = self.client.post(
            self.toggle_url,
            {"reason": "Super admin deactivation"},
        )
        self.assertEqual(toggle.status_code, 302)
        self.customer.user.refresh_from_db()
        self.assertFalse(self.customer.user.is_active)

        verify = self.client.post(
            self.verify_url,
            {"verification_status": VerificationStatus.VERIFIED},
        )
        self.assertEqual(verify.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.verification_status, VerificationStatus.VERIFIED
        )

    def test_admin_requires_view_customer_to_list_and_detail(self):
        self.client.login(username="cust-admin", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url).status_code, 403)

        self._login_admin_with("view_customer")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)

    def test_admin_requires_add_customer_to_create(self):
        self._login_admin_with("view_customer")
        self.assertEqual(self.client.get(self.create_url).status_code, 403)

        self.admin.user_permissions.add(self._perm("add_customer"))
        self.assertEqual(self.client.get(self.create_url).status_code, 200)

        create = self.client.post(
            self.create_url,
            {
                "first_name": "New",
                "last_name": "Person",
                "username": "new-customer",
                "email": "new-customer@example.com",
                "phone_number": "",
                "password": "secure-password-123",
                "confirm_password": "secure-password-123",
                "notes": "",
            },
        )
        self.assertEqual(create.status_code, 302)
        self.assertTrue(
            Customer.objects.filter(user__username="new-customer").exists()
        )

    def test_admin_requires_change_customer_to_edit(self):
        self._login_admin_with("view_customer")
        self.assertEqual(self.client.get(self.edit_url).status_code, 403)

        self.admin.user_permissions.add(self._perm("change_customer"))
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)

        edit = self.client.post(
            self.edit_url,
            {
                "first_name": "Updated",
                "last_name": "Customer",
                "email": self.customer.user.email,
                "phone_number": "",
                "notes": "Updated notes",
            },
        )
        self.assertEqual(edit.status_code, 302)
        self.customer.refresh_from_db()
        self.customer.user.refresh_from_db()
        self.assertEqual(self.customer.user.first_name, "Updated")
        self.assertEqual(self.customer.notes, "Updated notes")

    def test_admin_requires_activate_customer_to_toggle_status(self):
        self._login_admin_with("view_customer")
        response = self.client.post(self.toggle_url)
        self.assertEqual(response.status_code, 403)
        self.customer.user.refresh_from_db()
        self.assertTrue(self.customer.user.is_active)

        self.admin.user_permissions.add(self._perm("activate_customer"))
        allowed = self.client.post(
            self.toggle_url,
            {"reason": "Inactive account cleanup"},
        )
        self.assertEqual(allowed.status_code, 302)
        self.customer.user.refresh_from_db()
        self.assertFalse(self.customer.user.is_active)

    def test_admin_requires_verify_customer_to_update_verification(self):
        self._login_admin_with("view_customer", "change_customer")
        response = self.client.post(
            self.verify_url,
            {"verification_status": VerificationStatus.VERIFIED},
        )
        self.assertEqual(response.status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.verification_status, VerificationStatus.UNVERIFIED
        )

        # change_customer alone must not allow verification updates via edit.
        edit = self.client.post(
            self.edit_url,
            {
                "first_name": self.customer.user.first_name or "End",
                "last_name": self.customer.user.last_name or "Customer",
                "email": self.customer.user.email,
                "phone_number": "",
                "notes": "no verify",
                "verification_status": VerificationStatus.VERIFIED,
            },
        )
        self.assertEqual(edit.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.verification_status, VerificationStatus.UNVERIFIED
        )

        self.admin.user_permissions.add(self._perm("verify_customer"))
        allowed = self.client.post(
            self.verify_url,
            {"verification_status": VerificationStatus.VERIFIED},
        )
        self.assertEqual(allowed.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.verification_status, VerificationStatus.VERIFIED
        )

    def test_activate_and_verify_require_post(self):
        self.client.login(username="cust-super", password="secure-password-123")
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)
        self.assertEqual(self.client.get(self.verify_url).status_code, 405)

    def test_customer_role_denied_management_views_even_with_django_perms(self):
        self.grant_customer_perms(
            self.customer_user,
            "view_customer",
            "add_customer",
            "change_customer",
            "activate_customer",
            "verify_customer",
        )
        self.client.login(
            username="managed-customer", password="secure-password-123"
        )
        for url in (
            self.list_url,
            self.detail_url,
            self.create_url,
            self.edit_url,
        ):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(self.toggle_url).status_code, 403)
        self.assertEqual(
            self.client.post(
                self.verify_url,
                {"verification_status": VerificationStatus.VERIFIED},
            ).status_code,
            403,
        )

    def test_dashboard_module_requires_view_customer(self):
        dashboard_url = reverse("accounts:management_dashboard")
        self.client.login(username="cust-admin", password="secure-password-123")
        denied = self.client.get(dashboard_url)
        self.assertEqual(denied.status_code, 200)
        self.assertNotContains(denied, "Open Module")
        # Customers card should not appear without view_customer
        # (module hidden when can_access_module is False)
        self.assertNotContains(denied, reverse("customers:customer_list"))

        self.grant_customer_perms(self.admin, "view_customer")
        self.client.login(username="cust-admin", password="secure-password-123")
        allowed = self.client.get(dashboard_url)
        self.assertContains(allowed, reverse("customers:customer_list"))
