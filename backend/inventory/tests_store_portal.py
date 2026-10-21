from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from catalog.models import Product, ProductCategory, ProductStatus
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType, StoreUser

from .models import InventoryTransaction, InventoryTransactionType, PurchaseEntry

User = get_user_model()


def _purchase_post_payload(client, create_url, payload):
    response = client.get(create_url)
    token = response.context["form"]["submission_token"].value()
    data = dict(payload)
    data["submission_token"] = token
    return data


class StorePortalInventoryIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()

        def make_store(name):
            address = Address.objects.create(
                line1=f"{name} Road",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                latitude=Decimal("12.971600"),
                longitude=Decimal("77.594600"),
            )
            return Store.objects.create(
                name=name,
                store_type=StoreType.OWN_STORE,
                status=StoreStatus.ACTIVE,
                is_active=True,
                commission_percentage=Decimal("5.00"),
                address=address,
                category=StoreCategory.objects.create(name=f"Cat-{name}"),
            )

        self.store_a = make_store("Portal Store A")
        self.store_b = make_store("Portal Store B")
        category = ProductCategory.objects.create(name="Portal Goods")

        def make_product(store, sku, name, stock="10.000", threshold="2.000"):
            product = Product(
                store=store,
                name=name,
                sku=sku,
                category=category,
                store_price=Decimal("20.00"),
                status=ProductStatus.APPROVED,
                stock_quantity=Decimal(stock),
                low_stock_threshold=Decimal(threshold),
            )
            product.full_clean()
            product.save()
            return product

        self.product_a = make_product(self.store_a, "PA-1", "Alpha Juice")
        self.product_a_low = make_product(
            self.store_a, "PA-LOW", "Low Juice", stock="1.000", threshold="5.000"
        )
        self.product_a_zero = make_product(
            self.store_a, "PA-ZERO", "Empty Juice", stock="0.000"
        )
        self.product_b = make_product(self.store_b, "PB-1", "Beta Juice")

        self.manager = User.objects.create_user(
            username="store-mgr",
            email="store-mgr@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.manager,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
        )
        self.viewer = User.objects.create_user(
            username="store-viewer",
            email="store-viewer@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_a,
            user=self.viewer,
            is_primary=False,
            is_active=True,
            can_manage_inventory=False,
        )
        self.other_manager = User.objects.create_user(
            username="store-b-mgr",
            email="store-b-mgr@example.com",
            password="secure-password-123",
            role=Role.STORE_USER,
        )
        StoreUser.objects.create(
            store=self.store_b,
            user=self.other_manager,
            is_primary=True,
            is_active=True,
            can_manage_inventory=True,
        )

        self.list_url = reverse("inventory:store_inventory_list")
        self.detail_a = reverse(
            "inventory:store_product_inventory",
            kwargs={"product_id": self.product_a.pk},
        )
        self.detail_b = reverse(
            "inventory:store_product_inventory",
            kwargs={"product_id": self.product_b.pk},
        )
        self.stock_in_a = reverse(
            "inventory:store_product_stock_in",
            kwargs={"product_id": self.product_a.pk},
        )
        self.stock_in_b = reverse(
            "inventory:store_product_stock_in",
            kwargs={"product_id": self.product_b.pk},
        )
        self.stock_out_a = reverse(
            "inventory:store_product_stock_out",
            kwargs={"product_id": self.product_a.pk},
        )
        self.adjust_a = reverse(
            "inventory:store_product_adjust",
            kwargs={"product_id": self.product_a.pk},
        )
        self.damage_a = reverse(
            "inventory:store_product_damage",
            kwargs={"product_id": self.product_a.pk},
        )
        self.expire_a = reverse(
            "inventory:store_product_expire",
            kwargs={"product_id": self.product_a.pk},
        )
        self.purchase_list = reverse("inventory:store_purchase_list")
        self.purchase_create = reverse("inventory:store_purchase_create")

    def test_list_only_shows_own_store_with_stock_indicators(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product_a.name)
        self.assertContains(response, "Low stock")
        self.assertContains(response, "Out of stock")
        self.assertNotContains(response, self.product_b.name)

        response = self.client.get(self.list_url, {"stock": "low_stock"})
        self.assertContains(response, self.product_a_low.sku)
        self.assertNotContains(response, self.product_a.sku)

    def test_foreign_product_url_returns_404_for_all_actions(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        self.assertEqual(self.client.get(self.detail_b).status_code, 404)
        for name in (
            "store_product_stock_in",
            "store_product_stock_out",
            "store_product_adjust",
            "store_product_damage",
            "store_product_expire",
        ):
            url = reverse(f"inventory:{name}", kwargs={"product_id": self.product_b.pk})
            self.assertEqual(self.client.get(url).status_code, 404, name)
            self.assertEqual(
                self.client.post(
                    url,
                    {"quantity": "1.000", "reason": "x", "direction": "IN"},
                ).status_code,
                404,
                name,
            )

    def test_viewer_without_can_manage_inventory_can_view_but_not_write(self):
        self.client.login(username="store-viewer", password="secure-password-123")
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_a).status_code, 200)
        self.assertEqual(self.client.get(self.purchase_list).status_code, 200)
        for url in (
            self.stock_in_a,
            self.stock_out_a,
            self.adjust_a,
            self.damage_a,
            self.expire_a,
            self.purchase_create,
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_stock_in_uses_service_and_prg_avoids_duplicate_on_get(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        before = self.product_a.stock_quantity
        response = self.client.post(
            self.stock_in_a,
            {"quantity": "2.000", "reason": "Receive delivery"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse(
                "inventory:store_product_inventory",
                kwargs={"product_id": self.product_a.pk},
            ),
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, before + Decimal("2.000"))
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product_a,
                transaction_type=InventoryTransactionType.STOCK_IN,
            ).count(),
            1,
        )
        # Refreshing the success page is a GET and must not create another txn.
        self.client.get(response.url)
        self.assertEqual(
            InventoryTransaction.objects.filter(
                product=self.product_a,
                transaction_type=InventoryTransactionType.STOCK_IN,
            ).count(),
            1,
        )

    def test_stock_out_cannot_go_negative(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        response = self.client.post(
            self.stock_out_a,
            {"quantity": "999.000", "reason": "Too much"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("10.000"))

    def test_adjust_damage_expire_require_reason_and_reduce_stock(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        for url in (self.adjust_a, self.damage_a, self.expire_a):
            response = self.client.post(url, {"quantity": "1.000", "direction": "OUT"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)

        self.client.post(
            self.adjust_a,
            {"quantity": "1.000", "reason": "Cycle", "direction": "OUT"},
        )
        self.client.post(self.damage_a, {"quantity": "1.000", "reason": "Broken"})
        self.client.post(self.expire_a, {"quantity": "1.000", "reason": "Past date"})
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, Decimal("7.000"))

    def test_purchase_increases_stock_once_and_ignores_forged_store(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        before_a = self.product_a.stock_quantity
        before_b = self.product_b.stock_quantity
        response = self.client.post(
            self.purchase_create,
            _purchase_post_payload(
                self.client,
                self.purchase_create,
                {
                    "supplier_name": "Farm Co",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product_a.pk,
                    "quantity": "4.000",
                    "unit_cost": "2.50",
                    "store": self.store_b.pk,
                    "store_id": self.store_b.pk,
                },
            ),
        )
        self.assertEqual(response.status_code, 302)
        entry = PurchaseEntry.objects.get()
        self.assertEqual(entry.store_id, self.store_a.pk)
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_a.stock_quantity, before_a + Decimal("4.000"))
        self.assertEqual(self.product_b.stock_quantity, before_b)
        self.assertEqual(
            InventoryTransaction.objects.filter(purchase_entry=entry).count(),
            1,
        )
        txn = InventoryTransaction.objects.get(purchase_entry=entry)
        self.assertEqual(txn.unit_cost, Decimal("2.50"))
        self.assertEqual(txn.transaction_type, InventoryTransactionType.PURCHASE)
        # GET detail after redirect does not duplicate.
        detail = self.client.get(
            reverse("inventory:store_purchase_detail", kwargs={"pk": entry.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            InventoryTransaction.objects.filter(purchase_entry=entry).count(),
            1,
        )

    def test_cannot_purchase_foreign_product_or_view_foreign_purchase(self):
        self.client.login(username="store-b-mgr", password="secure-password-123")
        response = self.client.post(
            reverse("inventory:store_purchase_create"),
            _purchase_post_payload(
                self.client,
                reverse("inventory:store_purchase_create"),
                {
                    "supplier_name": "Other",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product_b.pk,
                    "quantity": "1.000",
                    "unit_cost": "1.00",
                },
            ),
        )
        self.assertEqual(response.status_code, 302)
        entry_b = PurchaseEntry.objects.get(store=self.store_b)

        self.client.login(username="store-mgr", password="secure-password-123")
        bad = self.client.post(
            self.purchase_create,
            _purchase_post_payload(
                self.client,
                self.purchase_create,
                {
                    "supplier_name": "Hack",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product_b.pk,
                    "quantity": "1.000",
                    "unit_cost": "1.00",
                },
            ),
        )
        self.assertEqual(bad.status_code, 200)
        self.assertTrue(bad.context["form"].errors)
        self.assertEqual(
            self.client.get(
                reverse("inventory:store_purchase_detail", kwargs={"pk": entry_b.pk})
            ).status_code,
            404,
        )

    def test_detail_shows_current_stock_and_history(self):
        self.client.login(username="store-mgr", password="secure-password-123")
        self.client.post(self.stock_in_a, {"quantity": "1.000"})
        response = self.client.get(self.detail_a)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current stock")
        self.assertContains(response, "Movement history")
        txn = InventoryTransaction.objects.filter(product=self.product_a).latest("pk")
        self.assertContains(response, txn.transaction_number)
        self.assertContains(response, str(txn.previous_quantity))
        self.assertContains(response, str(txn.new_quantity))
