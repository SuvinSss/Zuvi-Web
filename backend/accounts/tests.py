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
        self.assertEqual(admin.role, Role.SUPER_ADMIN)
        self.assertTrue(admin.check_password("secure-password-123"))

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

    def test_customer_role_rejects_staff_or_superuser(self):
        user = User(
            username="staff-customer",
            email="staff-customer@example.com",
            role=Role.CUSTOMER,
            is_staff=True,
            is_superuser=False,
        )
        user.set_password("secure-password-123")
        with self.assertRaises(ValidationError):
            user.full_clean()

        user.is_staff = False
        user.is_superuser = True
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_customer_profile_user_cannot_change_role(self):
        from customers.models import RegistrationSource
        from customers.services import create_customer_with_user

        customer, user = create_customer_with_user(
            user_data={
                "username": "locked-customer",
                "email": "locked-customer@example.com",
                "first_name": "Lock",
                "last_name": "Down",
                "phone_number": "9000000099",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        user.role = Role.ADMIN
        user.is_staff = True
        with self.assertRaises(ValidationError):
            user.full_clean()
        self.assertEqual(customer.user_id, user.pk)


class UserAdminCustomerInvariantTests(TestCase):
    def test_user_admin_forces_customer_invariants(self):
        from django.contrib.admin.sites import AdminSite

        from accounts.admin import UserAdmin
        from customers.models import RegistrationSource
        from customers.services import create_customer_with_user

        customer, user = create_customer_with_user(
            user_data={
                "username": "admin-edit-customer",
                "email": "admin-edit-customer@example.com",
                "first_name": "Admin",
                "last_name": "Edit",
                "phone_number": "9000000088",
                "password": "secure-password-123",
            },
            registration_source=RegistrationSource.WEBSITE,
        )
        actor = User.objects.create_superuser(
            username="invariant-super",
            email="invariant-super@example.com",
            password="secure-password-123",
        )
        request = type("Request", (), {"user": actor})()
        admin = UserAdmin(User, AdminSite())

        user.role = Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        admin.save_model(request, user, form=None, change=True)

        user.refresh_from_db()
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(customer.user_id, user.pk)

        readonly = admin.get_readonly_fields(request, obj=user)
        self.assertIn("role", readonly)
        self.assertIn("is_staff", readonly)
        self.assertIn("is_superuser", readonly)


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


    def _login_super_admin(self):
        self.client.login(username="manager-super", password="secure-password-123")












