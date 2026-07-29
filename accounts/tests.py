from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import AdminAuditLog, AdminProfile, Role

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="secure-password-123",
        )
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secure-password-123",
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_password_is_hashed(self):
        plain = "secure-password-123"
        user = User.objects.create_user(
            username="bob",
            email="bob@example.com",
            password=plain,
        )
        self.assertNotEqual(user.password, plain)
        self.assertTrue(user.check_password(plain))

    def test_email_must_be_unique(self):
        User.objects.create_user(
            username="first",
            email="shared@example.com",
            password="secure-password-123",
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username="second",
                email="shared@example.com",
                password="secure-password-123",
            )

    def test_default_role_is_customer(self):
        user = User.objects.create_user(
            username="carol",
            email="carol@example.com",
            password="secure-password-123",
        )
        self.assertEqual(user.role, Role.CUSTOMER)


class AdminProfileModelTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="super",
            email="super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin_user = User.objects.create_user(
            username="admin-user",
            email="admin-user@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username="customer-user",
            email="customer-user@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )

    def test_profile_is_valid_for_admin_role(self):
        profile = AdminProfile(
            user=self.admin_user,
            employee_id="EMP-1001",
            designation="Operations Admin",
            notes="Handles operations dashboards.",
            created_by=self.super_admin,
        )
        profile.full_clean()
        profile.save()
        self.assertEqual(profile.user, self.admin_user)

    def test_profile_is_valid_for_super_admin_role(self):
        profile = AdminProfile(
            user=self.super_admin,
            employee_id="EMP-1002",
            created_by=self.super_admin,
        )
        profile.full_clean()
        profile.save()
        self.assertEqual(profile.user.role, Role.SUPER_ADMIN)

    def test_profile_rejects_non_admin_roles(self):
        profile = AdminProfile(user=self.customer, created_by=self.super_admin)
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_employee_id_must_be_unique(self):
        AdminProfile.objects.create(
            user=self.admin_user,
            employee_id="EMP-2001",
            created_by=self.super_admin,
        )
        second_admin = User.objects.create_user(
            username="admin-user-2",
            email="admin-user-2@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        with self.assertRaises(IntegrityError):
            AdminProfile.objects.create(
                user=second_admin,
                employee_id="EMP-2001",
                created_by=self.super_admin,
            )


class AdminAuditLogModelTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="audit-super",
            email="audit-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin_user = User.objects.create_user(
            username="audit-admin",
            email="audit-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )

    def test_create_audit_log_with_defaults(self):
        log = AdminAuditLog.objects.create(
            actor=self.super_admin,
            action=AdminAuditLog.Action.ADMIN_CREATED,
            target_user=self.admin_user,
            description="Created new admin account.",
        )
        self.assertEqual(log.metadata, {})
        self.assertIsNone(log.ip_address)

    def test_audit_log_accepts_metadata_and_ip(self):
        log = AdminAuditLog.objects.create(
            actor=self.super_admin,
            action=AdminAuditLog.Action.PERMISSION_ASSIGNED,
            target_user=self.admin_user,
            description="Assigned permission to admin.",
            metadata={"permission": "accounts.change_user"},
            ip_address="127.0.0.1",
        )
        self.assertEqual(log.metadata["permission"], "accounts.change_user")
        self.assertEqual(log.ip_address, "127.0.0.1")


class ManagementPortalAccessTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="portal-super",
            email="portal-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin_user = User.objects.create_user(
            username="portal-admin",
            email="portal-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
        )
        self.customer = User.objects.create_user(
            username="portal-customer",
            email="portal-customer@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )
        self.store_user = User.objects.create_user(
            username="portal-store",
            email="portal-store@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        self.inactive_admin = User.objects.create_user(
            username="portal-inactive-admin",
            email="portal-inactive-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_active=False,
        )
        self.login_url = reverse("accounts:management_login")
        self.dashboard_url = reverse("accounts:management_dashboard")
        self.logout_url = reverse("accounts:management_logout")
        self.stores_permission = Permission.objects.get(
            codename="view_store",
            content_type__app_label="stores",
        )
        self.orders_permission = Permission.objects.get(codename="access_orders_module")

    def test_super_admin_access(self):
        self.client.login(username="portal-super", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Accounts")
        self.assertContains(response, "Stores")
        self.assertContains(response, "Products")
        self.assertContains(response, "Inventory")
        self.assertContains(response, "Customers")
        self.assertContains(response, "Orders")
        self.assertContains(response, "Delivery")

    def test_admin_access(self):
        self.client.login(username="portal-admin", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Admin Accounts")

    def test_admin_without_staff_flag_cannot_access_management_portal(self):
        self.admin_user.is_staff = False
        self.admin_user.save(update_fields=["is_staff"])
        response = self.client.post(
            self.login_url,
            {"username": "portal-admin", "password": "secure-password-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This account cannot access the management portal.")

    def test_customer_denied(self):
        self.client.login(username="portal-customer", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_store_user_denied(self):
        self.client.login(username="portal-store", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_inactive_admin_denied(self):
        response = self.client.post(
            self.login_url,
            {"username": "portal-inactive-admin", "password": "secure-password-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        dashboard_response = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard_response.status_code, 302)

    def test_anonymous_user_redirected(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(self.login_url))

    def test_logout_ends_session(self):
        self.client.login(username="portal-admin", password="secure-password-123")
        dashboard_before_logout = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard_before_logout.status_code, 200)
        logout_response = self.client.post(self.logout_url)
        self.assertEqual(logout_response.status_code, 302)
        self.assertEqual(logout_response.url, self.login_url)
        dashboard_after_logout = self.client.get(self.dashboard_url)
        self.assertEqual(dashboard_after_logout.status_code, 302)

    def test_logout_get_is_not_allowed(self):
        self.client.login(username="portal-admin", password="secure-password-123")
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 405)

    def test_admin_sees_only_modules_with_permissions(self):
        operations_group = Group.objects.create(name="Operations")
        operations_group.permissions.add(self.stores_permission, self.orders_permission)
        self.admin_user.groups.add(operations_group)
        self.client.login(username="portal-admin", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operations")
        self.assertContains(response, "Stores")
        self.assertContains(response, "Orders")
        self.assertNotContains(response, "Products")
        self.assertNotContains(response, "Inventory")
        self.assertNotContains(response, "Customers")
        self.assertNotContains(response, "Delivery")
        self.assertNotContains(response, "Admin Accounts")

    def test_admin_without_module_permissions_does_not_see_placeholder_cards(self):
        self.client.login(username="portal-admin", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No groups assigned.")
        self.assertNotContains(response, "Stores")
        self.assertNotContains(response, "Products")
        self.assertNotContains(response, "Inventory")
        self.assertNotContains(response, "Customers")
        self.assertNotContains(response, "Orders")
        self.assertNotContains(response, "Delivery")


class ManagementDashboardStoreCardTests(TestCase):
    def setUp(self):
        from decimal import Decimal

        from locations.models import Address
        from stores.models import Store, StoreCategory, StoreStatus, StoreType

        self.Store = Store
        self.StoreStatus = StoreStatus

        self.super_admin = User.objects.create_user(
            username="dash-super",
            email="dash-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="dash-admin",
            email="dash-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.view_store = Permission.objects.get(
            codename="view_store",
            content_type__app_label="stores",
        )
        self.dashboard_url = reverse("accounts:management_dashboard")
        self.stores_url = reverse("stores:store_list")

        category = StoreCategory.objects.create(name="Dashboard Cat")

        def make_store(name, status):
            address = Address.objects.create(
                line1=f"{name} Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                latitude=Decimal("12.971600"),
                longitude=Decimal("77.594600"),
            )
            return Store.objects.create(
                name=name,
                store_type=StoreType.OWN_STORE,
                status=status,
                category=category,
                address=address,
                commission_percentage=Decimal("5.00"),
            )

        make_store("Pending One", StoreStatus.PENDING)
        make_store("Pending Two", StoreStatus.PENDING)
        make_store("Active One", StoreStatus.ACTIVE)
        make_store("Active Two", StoreStatus.ACTIVE)
        make_store("Active Three", StoreStatus.ACTIVE)
        make_store("Suspended One", StoreStatus.SUSPENDED)
        make_store("Rejected One", StoreStatus.REJECTED)

    def _assert_store_card_counts(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stores")
        self.assertContains(response, f'href="{self.stores_url}"')
        self.assertContains(response, "Total Stores:")
        self.assertContains(response, "Pending Stores:")
        self.assertContains(response, "Active Stores:")
        self.assertContains(response, "Suspended Stores:")
        stats = response.context["store_stats"]
        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["active"], 3)
        self.assertEqual(stats["suspended"], 1)
        self.assertContains(response, f"<strong>Total Stores:</strong> {stats['total']}")
        self.assertContains(
            response, f"<strong>Pending Stores:</strong> {stats['pending']}"
        )
        self.assertContains(
            response, f"<strong>Active Stores:</strong> {stats['active']}"
        )
        self.assertContains(
            response, f"<strong>Suspended Stores:</strong> {stats['suspended']}"
        )

    def test_store_card_hidden_for_admin_without_view_store(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.login(username="dash-admin", password="secure-password-123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["store_stats"])
        self.assertNotContains(response, "Stores")
        self.assertNotContains(response, "Total Stores")
        self.assertNotContains(response, "Pending Stores")
        store_table_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "stores_store" in query["sql"].lower()
        ]
        self.assertEqual(store_table_queries, [])

    def test_store_card_visible_with_counts_for_admin_with_view_store(self):
        self.admin.user_permissions.add(self.view_store)
        self.client.login(username="dash-admin", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self._assert_store_card_counts(response)

    def test_store_card_visible_with_counts_for_super_admin(self):
        self.client.login(username="dash-super", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self._assert_store_card_counts(response)

    def test_store_dashboard_stats_uses_single_aggregate_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from stores.services import get_store_dashboard_stats

        with CaptureQueriesContext(connection) as ctx:
            stats = get_store_dashboard_stats()

        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["active"], 3)
        self.assertEqual(stats["suspended"], 1)
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertIn("COUNT", ctx.captured_queries[0]["sql"].upper())


class ManagementDashboardProductCardTests(TestCase):
    def setUp(self):
        from decimal import Decimal

        from catalog.models import Product, ProductCategory, ProductStatus
        from locations.models import Address
        from stores.models import Store, StoreCategory, StoreStatus, StoreType

        self.Product = Product
        self.ProductStatus = ProductStatus

        self.super_admin = User.objects.create_user(
            username="prod-dash-super",
            email="prod-dash-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="prod-dash-admin",
            email="prod-dash-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.view_product = Permission.objects.get(
            codename="view_product",
            content_type__app_label="catalog",
        )
        self.dashboard_url = reverse("accounts:management_dashboard")
        self.products_url = reverse("catalog:product_list")

        store_category = StoreCategory.objects.create(name="Prod Dash Store Cat")
        address = Address.objects.create(
            line1="Dash Street",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("77.594600"),
        )
        self.store = Store.objects.create(
            name="Prod Dash Store",
            store_type=StoreType.OWN_STORE,
            status=StoreStatus.ACTIVE,
            category=store_category,
            address=address,
            commission_percentage=Decimal("5.00"),
        )
        category = ProductCategory.objects.create(name="Prod Dash Cat")

        def make_product(sku, status, stock, threshold):
            return Product.objects.create(
                store=self.store,
                name=f"Product {sku}",
                sku=sku,
                category=category,
                store_price=Decimal("10.00"),
                status=status,
                stock_quantity=stock,
                low_stock_threshold=threshold,
            )

        make_product("D1", ProductStatus.DRAFT, Decimal("5"), Decimal("2"))
        make_product("P1", ProductStatus.PENDING, Decimal("5"), Decimal("2"))
        make_product("P2", ProductStatus.PENDING, Decimal("1"), Decimal("2"))  # low stock
        make_product("A1", ProductStatus.APPROVED, Decimal("10"), Decimal("2"))
        make_product("A2", ProductStatus.APPROVED, Decimal("1"), Decimal("3"))  # low stock
        make_product("R1", ProductStatus.REJECTED, Decimal("0"), Decimal("2"))  # not low (0)

    def _assert_product_card_counts(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Products")
        self.assertContains(response, f'href="{self.products_url}"')
        self.assertContains(response, "Total Products:")
        self.assertContains(response, "Pending Products:")
        self.assertContains(response, "Approved Products:")
        self.assertContains(response, "Rejected Products:")
        self.assertContains(response, "Low-stock Products:")
        stats = response.context["product_stats"]
        self.assertEqual(stats["total"], 6)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["approved"], 2)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["low_stock"], 2)
        self.assertContains(
            response, f"<strong>Total Products:</strong> {stats['total']}"
        )
        self.assertContains(
            response, f"<strong>Pending Products:</strong> {stats['pending']}"
        )
        self.assertContains(
            response, f"<strong>Approved Products:</strong> {stats['approved']}"
        )
        self.assertContains(
            response, f"<strong>Rejected Products:</strong> {stats['rejected']}"
        )
        self.assertContains(
            response, f"<strong>Low-stock Products:</strong> {stats['low_stock']}"
        )

    def test_product_card_hidden_for_admin_without_view_product(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.login(username="prod-dash-admin", password="secure-password-123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["product_stats"])
        self.assertNotContains(response, "Total Products")
        self.assertNotContains(response, "Pending Products")
        self.assertNotContains(response, "Low-stock Products")
        product_table_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "catalog_product" in query["sql"].lower()
            and "COUNT" in query["sql"].upper()
        ]
        self.assertEqual(product_table_queries, [])

    def test_product_card_visible_with_counts_for_admin_with_view_product(self):
        self.admin.user_permissions.add(self.view_product)
        self.client.login(username="prod-dash-admin", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self._assert_product_card_counts(response)

    def test_product_card_visible_with_counts_for_super_admin(self):
        self.client.login(username="prod-dash-super", password="secure-password-123")
        response = self.client.get(self.dashboard_url)
        self._assert_product_card_counts(response)

    def test_product_dashboard_stats_uses_single_aggregate_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from catalog.services import get_product_dashboard_stats

        with CaptureQueriesContext(connection) as ctx:
            stats = get_product_dashboard_stats()

        self.assertEqual(stats["total"], 6)
        self.assertEqual(stats["draft"], 1)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["approved"], 2)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["low_stock"], 2)
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertIn("COUNT", ctx.captured_queries[0]["sql"].upper())


class SuperAdminAdminManagementTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="manager-super",
            email="manager-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin_user = User.objects.create_user(
            username="manager-admin",
            email="manager-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
            first_name="Jane",
            last_name="Admin",
        )
        self.admin_profile = AdminProfile.objects.create(
            user=self.admin_user,
            employee_id="EMP-4001",
            designation="Ops",
            notes="Primary admin",
            created_by=self.super_admin,
        )
        self.regular_admin = User.objects.create_user(
            username="regular-admin",
            email="regular-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
        )
        self.customer = User.objects.create_user(
            username="regular-customer",
            email="regular-customer@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )
        self.group = Group.objects.create(name="Ops Team")
        self.permission = Permission.objects.get(codename="view_user")

        self.list_url = reverse("accounts:admin_list")
        self.create_url = reverse("accounts:admin_create")
        self.detail_url = reverse("accounts:admin_detail", args=[self.admin_user.pk])
        self.edit_url = reverse("accounts:admin_edit", args=[self.admin_user.pk])
        self.toggle_url = reverse("accounts:admin_toggle_status", args=[self.admin_user.pk])

    def _login_super_admin(self):
        self.client.login(username="manager-super", password="secure-password-123")

    def test_super_admin_can_access_admin_management_views(self):
        self._login_super_admin()
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.create_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)

    def test_non_super_admins_are_denied(self):
        self.client.login(username="regular-admin", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.client.logout()
        self.client.login(username="regular-customer", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

    def test_anonymous_user_redirected_to_management_login(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/management/login/", response.url)

    def test_admin_list_supports_search_filter_and_pagination(self):
        self._login_super_admin()
        for i in range(12):
            user = User.objects.create_user(
                username=f"paged-admin-{i}",
                email=f"paged-admin-{i}@example.com",
                password="secure-password-123",
                role=Role.ADMIN,
                is_staff=True,
            )
            AdminProfile.objects.create(
                user=user,
                employee_id=f"EMP-P{i}",
                created_by=self.super_admin,
            )
        response = self.client.get(self.list_url, {"q": "EMP-4001", "is_active": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "manager-admin")

        page_response = self.client.get(self.list_url, {"page": 2})
        self.assertEqual(page_response.status_code, 200)
        self.assertTrue(page_response.context["page_obj"].has_previous())

    def test_create_admin_sets_required_fields_and_creates_audit_log(self):
        self._login_super_admin()
        response = self.client.post(
            self.create_url,
            {
                "first_name": "New",
                "last_name": "Manager",
                "username": "new-admin",
                "email": "new-admin@example.com",
                "phone_number": "999000111",
                "employee_id": "EMP-5001",
                "designation": "Operations",
                "notes": "Created in test.",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
                "groups": [self.group.pk],
                "user_permissions": [self.permission.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        created_user = User.objects.get(username="new-admin")
        self.assertEqual(created_user.role, Role.ADMIN)
        self.assertTrue(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)
        self.assertTrue(created_user.check_password("StrongPass123!"))
        self.assertEqual(created_user.groups.first().name, "Ops Team")
        self.assertEqual(created_user.user_permissions.first().codename, "view_user")
        self.assertTrue(AdminProfile.objects.filter(user=created_user, employee_id="EMP-5001").exists())
        self.assertTrue(
            AdminAuditLog.objects.filter(
                actor=self.super_admin,
                target_user=created_user,
                action=AdminAuditLog.Action.ADMIN_CREATED,
            ).exists()
        )

    def test_create_admin_validates_unique_fields(self):
        self._login_super_admin()
        response = self.client.post(
            self.create_url,
            {
                "first_name": "Jane",
                "last_name": "Admin",
                "username": "manager-admin",
                "email": "manager-admin@example.com",
                "phone_number": "123123123",
                "employee_id": "EMP-4001",
                "designation": "Ops",
                "notes": "",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in use")

    def test_edit_admin_updates_profile_groups_permissions_and_creates_audit(self):
        self._login_super_admin()
        response = self.client.post(
            self.edit_url,
            {
                "first_name": "Janet",
                "last_name": "Admin",
                "username": "manager-admin",
                "email": "manager-admin@example.com",
                "phone_number": "222333444",
                "employee_id": "EMP-4001A",
                "designation": "Senior Ops",
                "notes": "Updated admin record",
                "groups": [self.group.pk],
                "user_permissions": [self.permission.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.admin_user.refresh_from_db()
        self.admin_profile.refresh_from_db()
        self.assertEqual(self.admin_user.first_name, "Janet")
        self.assertEqual(self.admin_profile.designation, "Senior Ops")
        self.assertEqual(self.admin_profile.employee_id, "EMP-4001A")
        self.assertEqual(self.admin_user.groups.first().name, "Ops Team")
        self.assertEqual(self.admin_user.user_permissions.first().codename, "view_user")
        self.assertTrue(
            AdminAuditLog.objects.filter(
                actor=self.super_admin,
                target_user=self.admin_user,
                action=AdminAuditLog.Action.ADMIN_UPDATED,
            ).exists()
        )

    def test_edit_page_does_not_expose_password_hash(self):
        self._login_super_admin()
        response = self.client.get(self.edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.admin_user.password)
        self.assertNotContains(response, "name=\"password\"")

    def test_toggle_status_requires_post(self):
        self._login_super_admin()
        response = self.client.get(self.toggle_url)
        self.assertEqual(response.status_code, 405)

    def test_toggle_status_deactivates_then_activates_with_audit_logs(self):
        self._login_super_admin()
        deactivate = self.client.post(self.toggle_url)
        self.assertEqual(deactivate.status_code, 302)
        self.admin_user.refresh_from_db()
        self.assertFalse(self.admin_user.is_active)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                target_user=self.admin_user,
                action=AdminAuditLog.Action.ADMIN_DEACTIVATED,
            ).exists()
        )

        activate = self.client.post(self.toggle_url)
        self.assertEqual(activate.status_code, 302)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.is_active)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                target_user=self.admin_user,
                action=AdminAuditLog.Action.ADMIN_ACTIVATED,
            ).exists()
        )

    def test_super_admin_cannot_deactivate_self(self):
        self._login_super_admin()
        self_toggle_url = reverse("accounts:admin_toggle_status", args=[self.super_admin.pk])
        response = self.client.post(self_toggle_url)
        self.assertEqual(response.status_code, 403)
