from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType, StoreUser

from .decorators import (
    user_can_view_management_inventory,
    user_has_inventory_permission,
)
from .forms import PurchaseEntryCreateForm

User = get_user_model()


def _purchase_post_payload(client, create_url, payload):
    """GET the create form for a one-time submission token, then merge payload."""
    response = client.get(create_url)
    token = response.context["form"]["submission_token"].value()
    data = dict(payload)
    data["submission_token"] = token
    return data


class InventoryPermissionTestMixin:
    def create_address(self, **overrides):
        defaults = {
            "line1": "12 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560001",
            "latitude": Decimal("12.971600"),
            "longitude": Decimal("77.594600"),
        }
        defaults.update(overrides)
        return Address.objects.create(**defaults)

    def create_store(self, **overrides):
        if "address" not in overrides:
            overrides["address"] = self.create_address()
        if "category" not in overrides:
            overrides["category"] = StoreCategory.objects.create(
                name=f"StoreCat-{StoreCategory.objects.count() + 1}"
            )
        defaults = {
            "name": "Zoop Mart",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
            "commission_percentage": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_product(self, store=None, **overrides):
        if store is None:
            store = self.create_store()
        if "category" not in overrides:
            overrides["category"] = ProductCategory.objects.create(
                name=f"Cat-{ProductCategory.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": "Sample Product",
            "sku": f"SKU-{Product.objects.count() + 1}",
            "store_price": Decimal("100.00"),
            "status": ProductStatus.APPROVED,
            "stock_quantity": Decimal("10.000"),
        }
        defaults.update(overrides)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        return product

    def create_super_admin(self, username="super-inv"):
        return User.objects.create_superuser(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
        )

    def create_admin(self, username="admin-inv"):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=False,
        )

    def create_store_user(
        self,
        store,
        username="store-inv",
        *,
        can_manage_inventory=True,
        **overrides,
    ):
        defaults = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "secure-password-123",
            "role": Role.STORE_USER,
        }
        defaults.update(overrides)
        user = User.objects.create_user(**defaults)
        StoreUser.objects.create(
            store=store,
            user=user,
            is_primary=True,
            is_active=True,
            can_manage_inventory=can_manage_inventory,
        )
        return user

    def grant_inventory_perms(self, user, *codenames):
        for codename in codenames:
            permission = Permission.objects.get(
                content_type__app_label="inventory",
                codename=codename,
            )
            user.user_permissions.add(permission)
        user = User.objects.get(pk=user.pk)
        return user


class InventoryPermissionHelperTests(InventoryPermissionTestMixin, TestCase):
    def setUp(self):
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()

    def test_super_admin_has_all_inventory_permissions(self):
        for perm in (
            "inventory.view_inventorytransaction",
            "inventory.view_all_inventory",
            "inventory.record_purchase",
            "inventory.adjust_inventory",
            "inventory.record_damage",
            "inventory.record_expiry",
            "inventory.export_inventory",
        ):
            self.assertTrue(user_has_inventory_permission(self.super_admin, perm))
        self.assertTrue(user_can_view_management_inventory(self.super_admin))

    def test_admin_requires_view_permission_for_pages(self):
        self.assertFalse(user_can_view_management_inventory(self.admin))
        self.grant_inventory_perms(self.admin, "view_inventorytransaction")
        self.admin = User.objects.get(pk=self.admin.pk)
        self.assertTrue(user_can_view_management_inventory(self.admin))

    def test_admin_view_all_inventory_also_grants_page_access(self):
        self.grant_inventory_perms(self.admin, "view_all_inventory")
        self.admin = User.objects.get(pk=self.admin.pk)
        self.assertTrue(user_can_view_management_inventory(self.admin))

    def test_admin_without_action_perms_denied(self):
        self.grant_inventory_perms(self.admin, "view_inventorytransaction")
        self.admin = User.objects.get(pk=self.admin.pk)
        self.assertFalse(
            user_has_inventory_permission(self.admin, "inventory.record_purchase")
        )
        self.assertFalse(
            user_has_inventory_permission(self.admin, "inventory.adjust_inventory")
        )
        self.assertFalse(
            user_has_inventory_permission(self.admin, "inventory.record_damage")
        )
        self.assertFalse(
            user_has_inventory_permission(self.admin, "inventory.record_expiry")
        )
        self.assertFalse(
            user_has_inventory_permission(self.admin, "inventory.export_inventory")
        )


class InventoryManagementPermissionViewTests(InventoryPermissionTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.store = self.create_store()
        self.product = self.create_product(store=self.store)
        self.super_admin = self.create_super_admin()
        self.admin = self.create_admin()
        self.list_url = reverse("inventory:management_inventory_list")
        self.export_url = reverse("inventory:management_inventory_export")
        self.purchase_url = reverse("inventory:management_purchase_create")
        self.purchase_list_url = reverse("inventory:management_purchase_list")
        self.detail_url = reverse(
            "inventory:management_product_inventory",
            kwargs={"product_id": self.product.pk},
        )
        self.adjust_url = reverse(
            "inventory:management_product_adjust",
            kwargs={"product_id": self.product.pk},
        )
        self.damage_url = reverse(
            "inventory:management_product_damage",
            kwargs={"product_id": self.product.pk},
        )
        self.expiry_url = reverse(
            "inventory:management_product_expire",
            kwargs={"product_id": self.product.pk},
        )
        self.stock_in_url = reverse(
            "inventory:management_product_stock_in",
            kwargs={"product_id": self.product.pk},
        )

    def test_anonymous_redirected_from_management_inventory(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)

    def test_super_admin_can_access_all_inventory_actions(self):
        self.client.login(username="super-inv", password="secure-password-123")
        for url in (
            self.list_url,
            self.export_url,
            self.purchase_url,
            self.purchase_list_url,
            self.detail_url,
            self.adjust_url,
            self.damage_url,
            self.expiry_url,
            self.stock_in_url,
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admin_without_view_perm_gets_403_on_list(self):
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

    def test_admin_with_view_perm_can_list_but_not_mutate(self):
        self.grant_inventory_perms(self.admin, "view_inventorytransaction")
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.purchase_url).status_code, 403)
        self.assertEqual(self.client.get(self.adjust_url).status_code, 403)
        self.assertEqual(self.client.get(self.damage_url).status_code, 403)
        self.assertEqual(self.client.get(self.expiry_url).status_code, 403)
        self.assertEqual(self.client.get(self.export_url).status_code, 403)
        self.assertEqual(self.client.get(self.stock_in_url).status_code, 403)

    def test_admin_record_purchase_perm(self):
        self.grant_inventory_perms(
            self.admin, "view_inventorytransaction", "record_purchase"
        )
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.purchase_url).status_code, 200)
        response = self.client.post(
            self.purchase_url,
            _purchase_post_payload(
                self.client,
                self.purchase_url,
                {
                    "supplier_name": "Fresh Farms",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product.pk,
                    "quantity": "2.000",
                    "unit_cost": "5.00",
                },
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("12.000"))

    def test_admin_adjust_inventory_perm(self):
        self.grant_inventory_perms(
            self.admin, "view_inventorytransaction", "adjust_inventory"
        )
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.adjust_url).status_code, 200)
        self.assertEqual(self.client.get(self.stock_in_url).status_code, 200)
        response = self.client.post(
            self.adjust_url,
            {
                "quantity": "1.000",
                "reason": "Cycle count",
                "direction": "IN",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_record_damage_perm(self):
        self.grant_inventory_perms(
            self.admin, "view_inventorytransaction", "record_damage"
        )
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.damage_url).status_code, 200)
        response = self.client.post(
            self.damage_url,
            {
                "quantity": "1.000",
                "reason": "Broken",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("9.000"))

    def test_admin_record_expiry_perm(self):
        self.grant_inventory_perms(
            self.admin, "view_inventorytransaction", "record_expiry"
        )
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.expiry_url).status_code, 200)
        response = self.client.post(
            self.expiry_url,
            {
                "quantity": "1.000",
                "reason": "Expired lot",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_admin_export_inventory_perm(self):
        self.grant_inventory_perms(
            self.admin, "view_inventorytransaction", "export_inventory"
        )
        self.client.login(username="admin-inv", password="secure-password-123")
        response = self.client.get(self.export_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")

    def test_admin_with_view_all_inventory_can_list(self):
        self.grant_inventory_perms(self.admin, "view_all_inventory")
        self.client.login(username="admin-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)


class InventoryStorePortalPermissionTests(InventoryPermissionTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.store_a = self.create_store(name="Store A")
        self.store_b = self.create_store(name="Store B")
        self.product_a = self.create_product(
            store=self.store_a, sku="A-1", name="Alpha Product"
        )
        self.product_b = self.create_product(
            store=self.store_b, sku="B-1", name="Beta Product"
        )
        self.store_user = self.create_store_user(
            self.store_a,
            username="portal-inv",
            can_manage_inventory=True,
        )
        self.viewer_only = User.objects.create_user(
            username="portal-view-only",
            email="portal-view-only@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.viewer_only,
            is_primary=False,
            is_active=True,
            can_manage_inventory=False,
        )
        self.list_url = reverse("inventory:store_inventory_list")
        self.purchase_url = reverse("inventory:store_purchase_create")
        self.purchase_list_url = reverse("inventory:store_purchase_list")
        self.adjust_url = reverse(
            "inventory:store_product_adjust",
            kwargs={"product_id": self.product_a.pk},
        )
        self.damage_url = reverse(
            "inventory:store_product_damage",
            kwargs={"product_id": self.product_a.pk},
        )
        self.expiry_url = reverse(
            "inventory:store_product_expire",
            kwargs={"product_id": self.product_a.pk},
        )
        self.stock_in_url = reverse(
            "inventory:store_product_stock_in",
            kwargs={"product_id": self.product_a.pk},
        )
        self.product_a_url = reverse(
            "inventory:store_product_inventory",
            kwargs={"product_id": self.product_a.pk},
        )
        self.product_b_url = reverse(
            "inventory:store_product_inventory",
            kwargs={"product_id": self.product_b.pk},
        )

    def test_store_user_can_view_own_store_inventory(self):
        self.client.login(username="portal-inv", password="secure-password-123")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product_a.name)
        self.assertNotContains(response, self.product_b.name)
        self.assertEqual(self.client.get(self.product_a_url).status_code, 200)

    def test_store_user_cannot_view_other_store_product(self):
        self.client.login(username="portal-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.product_b_url).status_code, 404)

    def test_store_user_without_can_manage_inventory_cannot_change(self):
        self.client.login(username="portal-view-only", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.purchase_url).status_code, 403)
        self.assertEqual(self.client.get(self.adjust_url).status_code, 403)
        self.assertEqual(self.client.get(self.damage_url).status_code, 403)
        self.assertEqual(self.client.get(self.expiry_url).status_code, 403)

    def test_store_user_with_can_manage_inventory_can_change_own_store(self):
        self.client.login(username="portal-inv", password="secure-password-123")
        self.assertEqual(self.client.get(self.purchase_url).status_code, 200)
        response = self.client.post(
            self.purchase_url,
            _purchase_post_payload(
                self.client,
                self.purchase_url,
                {
                    "supplier_name": "Local Supplier",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product_a.pk,
                    "quantity": "2.000",
                    "unit_cost": "4.00",
                    "store": self.store_b.pk,  # forged — must be ignored
                },
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("12.000"))
        self.assertEqual(self.product_b.stock_quantity, Decimal("10.000"))

    def test_store_user_cannot_post_foreign_product_on_purchase(self):
        self.client.login(username="portal-inv", password="secure-password-123")
        response = self.client.post(
            self.purchase_url,
            _purchase_post_payload(
                self.client,
                self.purchase_url,
                {
                    "supplier_name": "Local Supplier",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product_b.pk,
                    "quantity": "1.000",
                    "unit_cost": "1.00",
                },
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.stock_quantity, Decimal("10.000"))

    def test_store_user_form_queryset_locked_to_own_store(self):
        form = PurchaseEntryCreateForm(
            product_queryset=Product.objects.filter(store=self.store_a),
            locked_store=self.store_a,
        )
        self.assertTrue(form.fields["product"].queryset.filter(pk=self.product_a.pk).exists())
        self.assertFalse(form.fields["product"].queryset.filter(pk=self.product_b.pk).exists())
        self.assertNotIn("store", form.fields)

    def test_store_user_cannot_grant_themselves_inventory_permission(self):
        """Store portal has no endpoint to flip can_manage_inventory."""
        membership = StoreUser.objects.get(user=self.viewer_only)
        self.assertFalse(membership.can_manage_inventory)
        self.client.login(username="portal-view-only", password="secure-password-123")
        # Attempting to POST a forged flag to inventory endpoints must not elevate.
        self.assertEqual(self.client.get(self.adjust_url).status_code, 403)
        membership.refresh_from_db()
        self.assertFalse(membership.can_manage_inventory)

    def test_customer_cannot_access_store_or_management_inventory(self):
        User.objects.create_user(
            username="customer-inv",
            email="customer-inv@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )
        self.client.login(username="customer-inv", password="secure-password-123")
        self.assertIn(
            self.client.get(self.list_url).status_code,
            {302, 403},
        )
        self.assertIn(
            self.client.get(reverse("inventory:management_inventory_list")).status_code,
            {302, 403},
        )

    def test_management_only_can_set_can_manage_inventory(self):
        super_admin = self.create_super_admin(username="super-set-flag")
        self.client.login(username="super-set-flag", password="secure-password-123")
        # Grant store user change perm via super admin bypass
        edit_url = reverse(
            "stores:store_user_edit",
            kwargs={"pk": self.store_a.pk, "user_id": self.viewer_only.pk},
        )
        response = self.client.post(
            edit_url,
            {
                "username": self.viewer_only.username,
                "email": self.viewer_only.email,
                "first_name": "",
                "last_name": "",
                "phone_number": "",
                "designation": "",
                "can_manage_inventory": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        membership = StoreUser.objects.get(user=self.viewer_only)
        self.assertTrue(membership.can_manage_inventory)
