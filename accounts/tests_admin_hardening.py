"""Admin authorization, immutable history, and supported superuser bootstrap."""

import os
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product, ProductCategory, ProductPriceHistory, ProductStatusHistory
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatusHistory

from .models import AdminAuditLog, AdminProfile, Role, User

PASSWORD = "Local-test-only-password-492!"


def admin_url(model, action, obj=None):
    opts = model._meta
    return reverse(
        f"admin:{opts.app_label}_{opts.model_name}_{action}",
        args=[obj.pk] if obj is not None else None,
    )


class AdminClientMixin:
    def login_admin(self, user):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def post(self, url, data):
        return self.client.post(
            url, data, HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value
        )

    def request_for(self, user):
        request = RequestFactory().get("/admin/")
        request.user = user
        return request


class AdminAuthorizationTests(AdminClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.super_admin = User.objects.create_superuser(
            username="hardening-super", email="super@example.com", password=PASSWORD
        )
        cls.staff = User.objects.create_user(
            username="hardening-staff", email="staff@example.com", password=PASSWORD,
            role=Role.ADMIN, is_staff=True,
        )
        cls.staff.user_permissions.set(Permission.objects.all())
        cls.target = User.objects.create_user(
            username="hardening-target", email="target@example.com", password=PASSWORD,
            role=Role.ADMIN, is_staff=True,
        )
        cls.profile = AdminProfile.objects.create(user=cls.target, designation="Original")
        cls.group = Group.objects.create(name="Original group")
        cls.permission = Permission.objects.get(content_type__app_label="accounts", codename="change_user")

    def user_data(self, user):
        joined = timezone.localtime(user.date_joined)
        data = {
            "username": user.username, "email": user.email,
            "first_name": user.first_name, "last_name": user.last_name,
            "phone_number": user.phone_number or "", "role": user.role,
            "date_joined_0": joined.strftime("%Y-%m-%d"),
            "date_joined_1": joined.strftime("%H:%M:%S"),
            "groups": list(user.groups.values_list("pk", flat=True)),
            "user_permissions": list(user.user_permissions.values_list("pk", flat=True)),
        }
        for field in ("is_staff", "is_superuser", "is_active"):
            if getattr(user, field):
                data[field] = "on"
        return data

    def snapshot(self, user):
        return (
            User.objects.values().get(pk=user.pk),
            list(user.groups.values_list("pk", flat=True)),
            list(user.user_permissions.values_list("pk", flat=True)),
        )

    def test_staff_forged_user_privilege_posts_are_forbidden(self):
        self.login_admin(self.staff)
        for target in (self.staff, self.target, self.super_admin):
            before = self.snapshot(target)
            for changes in (
                {"role": Role.SUPER_ADMIN}, {"is_staff": ""},
                {"is_superuser": "on"}, {"is_active": ""},
                {"groups": [self.group.pk]}, {"user_permissions": [self.permission.pk]},
                {"password": "!"},
            ):
                with self.subTest(target=target.pk, changes=changes):
                    data = self.user_data(target)
                    data.update(changes)
                    self.assertEqual(self.post(admin_url(User, "change", target), data).status_code, 403)
                    self.assertEqual(self.snapshot(target), before)
        self.assertFalse(LogEntry.objects.exists())

    def test_staff_cannot_add_users_or_administer_passwords(self):
        self.login_admin(self.staff)
        before = User.objects.count()
        self.assertEqual(self.post(admin_url(User, "add"), {
            "username": "forged", "role": Role.SUPER_ADMIN,
            "is_staff": "on", "is_superuser": "on", "is_active": "on",
            "password1": PASSWORD, "password2": PASSWORD,
        }).status_code, 403)
        for target in (self.staff, self.target, self.super_admin):
            password = target.password
            url = reverse("admin:auth_user_password_change", args=[target.pk])
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.post(url, {
                "usable_password": "false", "unset-password": "1",
            }).status_code, 403)
            target.refresh_from_db()
            self.assertEqual(target.password, password)
        self.assertEqual(User.objects.count(), before)

    def test_staff_cannot_mutate_groups_or_admin_profiles(self):
        self.login_admin(self.staff)
        for model, obj, data in (
            (Group, self.group, {"name": "Forged", "permissions": [self.permission.pk]}),
            (AdminProfile, self.profile, {"user": self.target.pk, "designation": "Forged"}),
        ):
            before = list(model.objects.values())
            for action in ("add", "change", "delete"):
                with self.subTest(model=model.__name__, action=action):
                    url = admin_url(model, action, None if action == "add" else obj)
                    self.assertEqual(self.post(url, {**data, "post": "yes"}).status_code, 403)
            self.assertEqual(list(model.objects.values()), before)
        self.assertFalse(self.group.permissions.exists())

    def test_explicit_view_permission_is_read_only(self):
        self.login_admin(self.staff)
        for model, obj in ((User, self.target), (Group, self.group), (AdminProfile, self.profile)):
            response = self.client.get(admin_url(model, "change", obj))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context["has_change_permission"])
            self.assertFalse(response.context["has_delete_permission"])
        self.staff.user_permissions.set([self.permission])
        fresh_staff = User.objects.get(pk=self.staff.pk)
        self.assertFalse(admin.site._registry[User].has_view_permission(self.request_for(fresh_staff)))

    def test_inconsistent_or_inactive_roles_do_not_authorize_mutations(self):
        variants = (
            {"role": Role.ADMIN}, {"role": Role.CUSTOMER}, {"role": Role.STORE_USER},
            {"is_active": False}, {"is_staff": False}, {"is_superuser": False},
        )
        for variant in variants:
            actor = User(role=Role.SUPER_ADMIN, is_active=True, is_staff=True, is_superuser=True)
            for key, value in variant.items():
                setattr(actor, key, value)
            request = self.request_for(actor)
            for model in (User, Group, AdminProfile):
                with self.subTest(variant=variant, model=model.__name__):
                    registered = admin.site._registry[model]
                    self.assertFalse(registered.has_add_permission(request))
                    self.assertFalse(registered.has_change_permission(request))
                    self.assertFalse(registered.has_delete_permission(request))

    def test_super_admin_can_change_users_groups_profiles_and_logs_remain(self):
        self.login_admin(self.super_admin)
        data = self.user_data(self.target)
        data.update(first_name="Updated", groups=[self.group.pk], user_permissions=[self.permission.pk])
        response = self.post(admin_url(User, "change", self.target), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Updated")
        self.assertEqual(list(self.target.groups.all()), [self.group])
        self.assertEqual(list(self.target.user_permissions.all()), [self.permission])
        self.assertEqual(self.post(admin_url(Group, "change", self.group), {
            "name": self.group.name, "permissions": [self.permission.pk],
        }).status_code, 302)
        self.assertEqual(list(self.group.permissions.all()), [self.permission])
        self.assertEqual(self.post(admin_url(AdminProfile, "change", self.profile), {
            "user": self.target.pk, "designation": "Updated",
        }).status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.designation, "Updated")
        self.assertEqual(LogEntry.objects.filter(user=self.super_admin, action_flag=CHANGE).count(), 3)

    def test_super_admin_can_create_consistent_admin_accounts(self):
        self.login_admin(self.super_admin)
        for role in (Role.ADMIN, Role.SUPER_ADMIN):
            data = {
                "username": f"new-{role}", "email": f"new-{role}@example.com",
                "role": role, "is_staff": "on", "is_active": "on",
                "usable_password": "true", "password1": PASSWORD, "password2": PASSWORD,
            }
            if role == Role.SUPER_ADMIN:
                data["is_superuser"] = "on"
            response = self.post(admin_url(User, "add"), data)
            self.assertEqual(response.status_code, 302, getattr(response, "context", None))
            user = User.objects.get(username=data["username"])
            self.assertEqual(user.role, role)
            self.assertTrue(user.is_staff)
            self.assertEqual(user.is_superuser, role == Role.SUPER_ADMIN)
            self.assertTrue(user.check_password(PASSWORD))

    def test_self_cannot_remove_required_access(self):
        self.login_admin(self.super_admin)
        before = self.snapshot(self.super_admin)
        for field in ("role", "is_staff", "is_superuser", "is_active"):
            with self.subTest(field=field):
                data = self.user_data(self.super_admin)
                data[field] = Role.ADMIN if field == "role" else ""
                response = self.post(admin_url(User, "change", self.super_admin), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["adminform"].form.non_field_errors())
                self.assertEqual(self.snapshot(self.super_admin), before)
        self.assertFalse(LogEntry.objects.exists())

    def test_self_password_cannot_be_disabled_including_alternate_id(self):
        self.login_admin(self.super_admin)
        before = self.super_admin.password
        for identifier in (str(self.super_admin.pk), f"0{self.super_admin.pk}"):
            url = reverse("admin:auth_user_password_change", args=[identifier])
            self.assertEqual(self.post(url, {
                "usable_password": "false", "unset-password": "1",
            }).status_code, 403)
            self.super_admin.refresh_from_db()
            self.assertEqual(self.super_admin.password, before)
            self.assertEqual(self.client.session["_auth_user_id"], str(self.super_admin.pk))

    def test_legitimate_self_edit_and_password_change_keep_session(self):
        self.login_admin(self.super_admin)
        data = self.user_data(self.super_admin)
        data["first_name"] = "Updated"
        self.assertEqual(self.post(admin_url(User, "change", self.super_admin), data).status_code, 302)
        new_password = "Another-local-password-503!"
        url = reverse("admin:auth_user_password_change", args=[self.super_admin.pk])
        self.assertEqual(self.post(url, {
            "usable_password": "true", "password1": new_password, "password2": new_password,
        }).status_code, 302)
        self.super_admin.refresh_from_db()
        self.assertEqual(self.super_admin.first_name, "Updated")
        self.assertTrue(self.super_admin.check_password(new_password))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.super_admin.pk))
        self.assertEqual(LogEntry.objects.filter(user=self.super_admin, action_flag=CHANGE).count(), 2)

    def test_authentication_users_cannot_be_deleted_singly_or_in_bulk(self):
        self.login_admin(self.super_admin)
        customer = User.objects.create_user(username="undeletable", email="undeletable@example.com")
        for user in (customer, self.target, self.super_admin):
            self.assertEqual(self.post(admin_url(User, "delete", user), {"post": "yes"}).status_code, 403)
            self.post(admin_url(User, "changelist"), {
                "action": "delete_selected", "_selected_action": [user.pk], "post": "yes",
            })
            self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertEqual(admin.site._registry[User].get_actions(self.request_for(self.super_admin)), {})

    def test_csrf_is_still_required_for_authorized_mutations(self):
        self.login_admin(self.super_admin)
        self.assertEqual(self.client.post(admin_url(Group, "change", self.group), {
            "name": "No CSRF", "permissions": [self.permission.pk],
        }).status_code, 403)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Original group")


class ImmutableHistoryAdminTests(AdminClientMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.super_admin = User.objects.create_superuser(
            username="history-super", email="history@example.com", password=PASSWORD
        )
        cls.store = Store.objects.create(
            name="History store", store_type="OWN_STORE",
            category=StoreCategory.objects.create(name="History category"),
            address=Address.objects.create(
                line1="Test road", city="Test city", state="Test state", postal_code="123456",
                latitude=Decimal("10"), longitude=Decimal("76"),
            ),
        )
        cls.product = Product.objects.create(
            store=cls.store, name="History product", sku="HISTORY-1",
            category=ProductCategory.objects.create(name="History category"), store_price=Decimal("10"),
        )
        cls.records = (
            AdminAuditLog.objects.create(actor=cls.super_admin, action="ADMIN_UPDATED", description="Original"),
            StoreStatusHistory.objects.create(store=cls.store, new_status="PENDING", changed_by=cls.super_admin),
            ProductStatusHistory.objects.create(product=cls.product, new_status="DRAFT", changed_by=cls.super_admin),
            ProductPriceHistory.objects.create(product=cls.product, store_price=Decimal("10"), changed_by=cls.super_admin),
        )

    def setUp(self):
        self.login_admin(self.super_admin)

    def test_history_is_visible_but_direct_mutation_is_forbidden(self):
        for obj in self.records:
            model = type(obj)
            before = list(model.objects.values())
            with self.subTest(model=model.__name__):
                self.assertEqual(self.client.get(admin_url(model, "changelist")).status_code, 200)
                self.assertEqual(self.client.get(admin_url(model, "change", obj)).status_code, 200)
                for action in ("add", "change", "delete"):
                    url = admin_url(model, action, None if action == "add" else obj)
                    self.assertEqual(self.post(url, {
                        "post": "yes", "reason": "Forged", "description": "Forged", "store_price": "1",
                    }).status_code, 403)
                self.assertEqual(list(model.objects.values()), before)

    def test_history_bulk_deletion_is_disabled(self):
        for obj in self.records:
            model = type(obj)
            with self.subTest(model=model.__name__):
                before = list(model.objects.values())
                self.assertEqual(admin.site._registry[model].get_actions(self.request_for(self.super_admin)), {})
                self.post(admin_url(model, "changelist"), {
                    "action": "delete_selected", "_selected_action": [obj.pk], "post": "yes",
                })
                self.assertEqual(list(model.objects.values()), before)

    def test_parent_deletion_cannot_cascade_into_history(self):
        for parent in (self.product, self.store):
            with self.subTest(parent=type(parent).__name__):
                model = type(parent)
                _, _, missing_permissions, protected = admin.site._registry[model].get_deleted_objects(
                    [parent], self.request_for(self.super_admin)
                )
                self.assertTrue(missing_permissions)
                self.assertFalse(protected, "History permissions, not unrelated PROTECT rows, must block deletion.")
                self.assertEqual(self.post(admin_url(model, "delete", parent), {"post": "yes"}).status_code, 403)
                self.assertEqual(self.post(admin_url(model, "changelist"), {
                    "action": "delete_selected", "_selected_action": [parent.pk], "post": "yes",
                }).status_code, 403)
                self.assertTrue(model.objects.filter(pk=parent.pk).exists())
                for obj in self.records:
                    self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())

    def test_history_inlines_have_no_write_or_delete_permissions(self):
        from catalog.admin import ProductPriceHistoryInline, ProductStatusHistoryInline
        from stores.admin import StoreStatusHistoryInline

        request = self.request_for(self.super_admin)
        for inline_class, parent in (
            (StoreStatusHistoryInline, self.store),
            (ProductStatusHistoryInline, self.product),
            (ProductPriceHistoryInline, self.product),
        ):
            inline = inline_class(type(parent), admin.site)
            self.assertFalse(inline.has_add_permission(request, parent))
            self.assertFalse(inline.has_change_permission(request, parent))
            self.assertFalse(inline.has_delete_permission(request, parent))
            self.assertFalse(inline.can_delete)

    def test_existing_order_and_inventory_history_admins_remain_immutable(self):
        from inventory.models import InventoryTransaction
        from orders.models import OrderStatusHistory, StoreOrderStatusHistory

        request = self.request_for(self.super_admin)
        for model in (InventoryTransaction, OrderStatusHistory, StoreOrderStatusHistory):
            registered = admin.site._registry[model]
            self.assertTrue(registered.has_view_permission(request))
            self.assertFalse(registered.has_add_permission(request))
            self.assertFalse(registered.has_change_permission(request))
            self.assertFalse(registered.has_delete_permission(request))
            self.assertEqual(registered.get_actions(request), {})


class SuperuserBootstrapTests(TestCase):
    def test_standard_createsuperuser_command_sets_role_flags_and_password(self):
        output = StringIO()
        with patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": PASSWORD}):
            call_command("createsuperuser", username="bootstrap", email="bootstrap@example.com", interactive=False, stdout=output)
        user = User.objects.get(username="bootstrap")
        self.assertEqual(user.role, Role.SUPER_ADMIN)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)
        self.assertNotIn(PASSWORD, output.getvalue())

    def test_noninteractive_without_password_keeps_django_unusable_password_behavior(self):
        with patch.dict(os.environ):
            os.environ.pop("DJANGO_SUPERUSER_PASSWORD", None)
            call_command("createsuperuser", username="no-password", email="no-password@example.com", interactive=False, stdout=StringIO())
        user = User.objects.get(username="no-password")
        self.assertEqual(user.role, Role.SUPER_ADMIN)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.has_usable_password())

    def test_contradictory_superuser_arguments_fail_without_creating_accounts(self):
        for fields in ({"role": Role.ADMIN}, {"role": Role.CUSTOMER}, {"role": None}, {"is_staff": False}, {"is_superuser": False}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                User.objects.create_superuser(username="contradiction", email="contra@example.com", password=PASSWORD, **fields)
        self.assertFalse(User.objects.exists())

    def test_ordinary_create_user_semantics_are_unchanged(self):
        customer = User.objects.create_user(username="ordinary", email="ordinary@example.com", password=PASSWORD)
        self.assertEqual(customer.role, Role.CUSTOMER)
        self.assertFalse(customer.is_staff)
        self.assertFalse(customer.is_superuser)
        self.assertTrue(customer.check_password(PASSWORD))
        explicit = User.objects.create_user(username="explicit", email="explicit@example.com", role=Role.ADMIN, is_staff=True)
        self.assertEqual(explicit.role, Role.ADMIN)
        self.assertTrue(explicit.is_staff)
        self.assertFalse(explicit.is_superuser)
        self.assertFalse(explicit.has_usable_password())

    def test_async_superuser_creation_preserves_same_contract(self):
        user = async_to_sync(User.objects.acreate_superuser)(username="async-super", email="async@example.com", password=PASSWORD)
        self.assertEqual(user.role, Role.SUPER_ADMIN)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        for fields in ({"role": Role.ADMIN}, {"is_staff": False}, {"is_superuser": False}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                async_to_sync(User.objects.acreate_superuser)(username="async-invalid", email="invalid@example.com", password=PASSWORD, **fields)
        self.assertEqual(User.objects.count(), 1)
