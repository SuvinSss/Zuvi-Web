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

    def _login_admin_with(self, *codenames):
        self.grant_customer_perms(self.admin, *codenames)
        self.client.login(username="cust-admin", password="secure-password-123")









