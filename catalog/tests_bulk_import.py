from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from stores.models import StoreStatus
from .bulk_import import UNCATEGORISED, parse_unit
from .models import Product, ProductCategory, ProductStatus, ProductUnit
from .tests import CatalogTestMixin

User = get_user_model()


class ParseUnitTests(TestCase):
    def test_sizes(self):
        cases = {
            "CHAITHRAM 1 KG": (ProductUnit.KG, Decimal("1")),
            "PACHARI 1ST 500GM": (ProductUnit.GRAM, Decimal("500")),
            "ELITE MATTA BROKEN RICE.500G": (ProductUnit.GRAM, Decimal("500")),
            "7 STAR RICE 5KG BAG": (ProductUnit.KG, Decimal("5")),
            "Jeerakam 100gm": (ProductUnit.GRAM, Decimal("100")),
            "KLF COCONUT OIL 1 LTR": (ProductUnit.LITER, Decimal("1")),
            "GINGELLY OIL 500ML": (ProductUnit.ML, Decimal("500")),
            "SUNFLOWER OIL 1L POUCH": (ProductUnit.LITER, Decimal("1")),
            "OIL 1.5 Litre": (ProductUnit.LITER, Decimal("1.5")),
            "PAVIZHAM UNDA 10 BAG": (ProductUnit.PIECE, Decimal("1")),
            "BT RICE": (ProductUnit.PIECE, Decimal("1")),
            "5 GOLD RICE": (ProductUnit.PIECE, Decimal("1")),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(parse_unit(name), expected)


class BulkImportViewTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="bulk-admin",
            email="bulk-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store = self.create_store(name="Zuuvi Grocery")
        self.url = reverse("catalog:bulk_import_item")
        self.client.force_login(self.admin)

    def post(self, **overrides):
        data = {
            "store": self.store.pk,
            "sl_no": "1",
            "name": "CHAITHRAM 1 KG",
            "category": "Rice",
            "image": self._uploaded_image(),
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_workspace_preselects_default_store(self):
        response = self.client.get(reverse("catalog:bulk_import"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["default_store"], self.store.pk)

    def test_creates_pending_product_with_zero_price_and_image(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "created")
        product = Product.objects.get(store=self.store, sku="NP-0001")
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertEqual(product.store_price, Decimal("0"))
        self.assertEqual(product.stock_quantity, Decimal("0"))
        self.assertEqual((product.unit, product.unit_value), (ProductUnit.KG, Decimal("1")))
        self.assertEqual(product.category.name, "Rice")
        self.assertEqual(product.images.count(), 1)
        self.assertTrue(product.status_history.exists())

    def test_repeat_post_is_idempotent(self):
        self.post()
        response = self.post()
        self.assertEqual(response.json()["state"], "exists")
        self.assertEqual(Product.objects.count(), 1)

    def test_same_name_different_row_is_duplicate(self):
        self.post()
        response = self.post(sl_no="2", name="chaithram  1 kg")
        self.assertEqual(response.json()["state"], "duplicate")
        self.assertEqual(Product.objects.count(), 1)

    def test_existing_category_reused_and_blank_goes_to_uncategorised(self):
        rice = self.create_product_category(name="Rice")
        self.post()
        self.assertEqual(Product.objects.get(sku="NP-0001").category, rice)
        self.post(sl_no="2", name="Jeerakam 100gm", category="")
        self.assertEqual(Product.objects.get(sku="NP-0002").category.name, UNCATEGORISED)
        self.assertEqual(ProductCategory.objects.filter(name="Rice").count(), 1)

    def test_invalid_image_rolls_back(self):
        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        response = self.post(image=bad)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(ProductCategory.objects.filter(name="Rice").exists())

    def test_inactive_store_rejected(self):
        self.store.status = StoreStatus.SUSPENDED
        self.store.save()
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Product.objects.exists())

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_admin_without_permission_denied(self):
        admin = User.objects.create_user(
            username="plain-admin",
            email="plain-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.client.force_login(admin)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.client.get(reverse("catalog:bulk_import")).status_code, 403)
        self.assertFalse(Product.objects.exists())

    def test_admin_without_category_permission_cannot_create_category(self):
        admin = User.objects.create_user(
            username="product-admin",
            email="product-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.grant_catalog_perms(admin, "add_product")
        self.client.force_login(admin)
        self.assertEqual(self.post().status_code, 403)
        self.create_product_category(name="Rice")
        self.assertEqual(self.post().json()["state"], "created")

    def test_store_user_denied(self):
        self.client.force_login(self.create_store_user(self.store))
        self.assertIn(self.post().status_code, (302, 403))
        self.assertFalse(Product.objects.exists())
