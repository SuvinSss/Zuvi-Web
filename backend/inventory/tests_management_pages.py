from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AdminAuditLog, Role
from catalog.models import Product, ProductCategory, ProductStatus
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

from .models import InventoryTransaction, PurchaseEntry
from .services import record_manual_stock_in, record_manual_stock_out

User = get_user_model()


def _purchase_post_payload(client, create_url, payload):
    """GET the create form for a one-time submission token, then merge payload."""
    response = client.get(create_url)
    token = response.context["form"]["submission_token"].value()
    data = dict(payload)
    data["submission_token"] = token
    return data


class ManagementInventoryPagesTests(TestCase):
    def setUp(self):
        self.client = Client()
        address = Address.objects.create(
            line1="12 MG Road",
            city="Bengaluru",
            state="Karnataka",
            postal_code="560001",
            latitude=Decimal("12.971600"),
            longitude=Decimal("77.594600"),
        )
        category = StoreCategory.objects.create(name="Grocery")
        self.store = Store.objects.create(
            name="Zoop Mart",
            store_type=StoreType.OWN_STORE,
            status=StoreStatus.ACTIVE,
            is_active=True,
            commission_percentage=Decimal("5.00"),
            address=address,
            category=category,
        )
        product_category = ProductCategory.objects.create(name="Snacks")
        self.product = Product(
            store=self.store,
            name="Chips",
            sku="CHIP-1",
            category=product_category,
            store_price=Decimal("50.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=Decimal("10.000"),
            low_stock_threshold=Decimal("3.000"),
            expiry_date=timezone.localdate() + timedelta(days=5),
        )
        self.product.full_clean()
        self.product.save()

        self.zero_product = Product(
            store=self.store,
            name="Empty Box",
            sku="EMPTY-1",
            category=product_category,
            store_price=Decimal("10.00"),
            status=ProductStatus.APPROVED,
            stock_quantity=Decimal("0.000"),
            low_stock_threshold=Decimal("1.000"),
        )
        self.zero_product.full_clean()
        self.zero_product.save()

        self.super_admin = User.objects.create_superuser(
            username="mgmt-inv-super",
            email="mgmt-inv-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
        )
        self.admin = User.objects.create_user(
            username="mgmt-inv-admin",
            email="mgmt-inv-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        for codename in (
            "view_inventorytransaction",
            "adjust_inventory",
            "record_damage",
            "record_expiry",
            "record_purchase",
            "export_inventory",
        ):
            self.admin.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="inventory",
                    codename=codename,
                )
            )

        self.list_url = reverse("inventory:management_inventory_list")
        self.detail_url = reverse(
            "inventory:management_product_inventory",
            kwargs={"product_id": self.product.pk},
        )
        self.stock_in_url = reverse(
            "inventory:management_product_stock_in",
            kwargs={"product_id": self.product.pk},
        )
        self.stock_out_url = reverse(
            "inventory:management_product_stock_out",
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
        self.expire_url = reverse(
            "inventory:management_product_expire",
            kwargs={"product_id": self.product.pk},
        )
        self.purchase_list_url = reverse("inventory:management_purchase_list")
        self.purchase_create_url = reverse("inventory:management_purchase_create")

    def test_list_columns_filters_and_pagination_context(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.product_code)
        self.assertContains(response, self.product.sku)
        self.assertContains(response, "Stock status")
        self.assertContains(response, "In stock")

        response = self.client.get(self.list_url, {"stock": "out_of_stock"})
        self.assertContains(response, self.zero_product.name)
        self.assertNotContains(response, self.product.sku)

        response = self.client.get(self.list_url, {"stock": "low_stock"})
        # 10 > threshold 3, so Chips not low; seed a low item via balance change through service
        record_manual_stock_out(
            product=self.product,
            store=self.store,
            quantity=Decimal("8.000"),
            actor=self.admin,
            reason="Bring into low stock band",
        )
        response = self.client.get(self.list_url, {"stock": "low_stock"})
        self.assertContains(response, self.product.sku)

        response = self.client.get(self.list_url, {"stock": "expiring"})
        self.assertContains(response, self.product.sku)

        response = self.client.get(self.list_url, {"q": self.product.product_code})
        self.assertContains(response, self.product.name)

    def test_detail_shows_history_balances_and_purchase_section(self):
        record_manual_stock_in(
            product=self.product,
            store=self.store,
            quantity=Decimal("1.000"),
            actor=self.admin,
        )
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transaction history")
        self.assertContains(response, "Purchase history")
        self.assertContains(response, "Previous")
        txn = InventoryTransaction.objects.latest("pk")
        self.assertContains(response, txn.transaction_number)
        self.assertContains(response, str(txn.previous_quantity))
        self.assertContains(response, str(txn.new_quantity))

    def test_stock_changes_require_post_and_use_service(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        before = self.product.stock_quantity
        self.assertEqual(self.client.get(self.stock_in_url).status_code, 200)
        response = self.client.post(
            self.stock_in_url,
            {"quantity": "2.000", "reason": "Receive"},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before + Decimal("2.000"))
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.INVENTORY_STOCK_IN
            ).exists()
        )

    def test_audit_ip_ignores_spoofed_x_forwarded_for(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        response = self.client.post(
            self.stock_in_url,
            {"quantity": "1.000", "reason": "IP spoof check"},
            HTTP_X_FORWARDED_FOR="203.0.113.50, 198.51.100.1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 302)
        audit = AdminAuditLog.objects.filter(
            action=AdminAuditLog.Action.INVENTORY_STOCK_IN,
        ).latest("created_at")
        self.assertEqual(audit.ip_address, "127.0.0.1")
        self.assertNotEqual(audit.ip_address, "203.0.113.50")

    def test_stock_out_adjust_damage_expire_require_reason(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        for url in (self.stock_out_url, self.adjust_url, self.damage_url, self.expire_url):
            response = self.client.post(url, {"quantity": "1.000", "direction": "OUT"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)

        response = self.client.post(
            self.adjust_url,
            {"quantity": "1.000", "reason": "Cycle", "direction": "OUT"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.INVENTORY_ADJUSTED
            ).exists()
        )

        response = self.client.post(
            self.damage_url,
            {"quantity": "1.000", "reason": "Broken pack"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.INVENTORY_DAMAGE_RECORDED
            ).exists()
        )

        response = self.client.post(
            self.expire_url,
            {"quantity": "1.000", "reason": "Past date"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.INVENTORY_EXPIRY_RECORDED
            ).exists()
        )

    def test_purchase_list_create_detail_and_audit(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        self.assertEqual(self.client.get(self.purchase_list_url).status_code, 200)
        response = self.client.post(
            self.purchase_create_url,
            _purchase_post_payload(
                self.client,
                self.purchase_create_url,
                {
                    "supplier_name": "Fresh Farms",
                    "entry_date": timezone.localdate().isoformat(),
                    "product": self.product.pk,
                    "quantity": "3.000",
                    "unit_cost": "12.50",
                },
            ),
        )
        self.assertEqual(response.status_code, 302)
        entry = PurchaseEntry.objects.get()
        detail = self.client.get(
            reverse("inventory:management_purchase_detail", kwargs={"pk": entry.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, entry.entry_number)
        self.assertContains(detail, "37.50")
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.PURCHASE_ENTRY_CONFIRMED
            ).exists()
        )

    def test_purchase_duplicate_submission_token_is_rejected(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        before = self.product.stock_quantity
        payload = _purchase_post_payload(
            self.client,
            self.purchase_create_url,
            {
                "supplier_name": "Fresh Farms",
                "entry_date": timezone.localdate().isoformat(),
                "product": self.product.pk,
                "quantity": "1.000",
                "unit_cost": "5.00",
            },
        )
        first = self.client.post(self.purchase_create_url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(PurchaseEntry.objects.count(), 1)
        self.product.refresh_from_db()
        after_first = self.product.stock_quantity
        self.assertEqual(after_first, before + Decimal("1.000"))
        replay = self.client.post(self.purchase_create_url, payload)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.context["form"].non_field_errors())
        self.assertEqual(PurchaseEntry.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, after_first)

    def test_super_admin_can_open_all_management_urls(self):
        self.client.login(username="mgmt-inv-super", password="secure-password-123")
        for url in (
            self.list_url,
            self.detail_url,
            self.stock_in_url,
            self.stock_out_url,
            self.adjust_url,
            self.damage_url,
            self.expire_url,
            self.purchase_list_url,
            self.purchase_create_url,
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_get_does_not_change_stock(self):
        self.client.login(username="mgmt-inv-admin", password="secure-password-123")
        before = self.product.stock_quantity
        self.client.get(self.stock_in_url)
        self.client.get(self.damage_url)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, before)
        self.assertEqual(InventoryTransaction.objects.count(), 0)
