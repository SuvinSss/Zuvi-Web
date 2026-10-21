from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Role
from catalog.models import (
    Brand,
    Product,
    ProductCategory,
    ProductImage,
    ProductStatus,
    ProductUnit,
    Tag,
)
from catalog.pricing import DiscountType, MarginType
from catalog.public import public_product_card, public_products_queryset
from customers.models import Customer, RegistrationSource
from inventory.services import record_manual_stock_in
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType

User = get_user_model()


class PublicCatalogueTestMixin:
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
            overrides["address"] = self.create_address(
                line1=f"Store addr {Address.objects.count() + 1}"
            )
        if "category" not in overrides:
            overrides["category"] = StoreCategory.objects.create(
                name=f"StoreCat-{StoreCategory.objects.count() + 1}"
            )
        defaults = {
            "name": f"Store {Store.objects.count() + 1}",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
            "commission_percentage": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_product_category(self, name=None, **overrides):
        defaults = {
            "name": name or f"Category {ProductCategory.objects.count() + 1}",
            "is_active": True,
        }
        defaults.update(overrides)
        category = ProductCategory(**defaults)
        category.full_clean()
        category.save()
        return category

    def create_brand(self, name=None, **overrides):
        defaults = {
            "name": name or f"Brand {Brand.objects.count() + 1}",
            "is_active": True,
        }
        defaults.update(overrides)
        brand = Brand(**defaults)
        brand.full_clean()
        brand.save()
        return brand

    def create_public_product(self, *, store=None, stock=Decimal("10.000"), **overrides):
        store = store or self.create_store()
        if "category" not in overrides:
            overrides["category"] = self.create_product_category()
        if "brand" not in overrides:
            overrides["brand"] = self.create_brand()
        defaults = {
            "store": store,
            "name": f"Public Product {Product.objects.count() + 1}",
            "sku": f"PUB-{Product.objects.count() + 1}",
            "store_price": Decimal("100.00"),
            "profit_margin_type": MarginType.FIXED,
            "profit_margin": Decimal("20.00"),
            "status": ProductStatus.APPROVED,
            "is_active": True,
            "unit": ProductUnit.PIECE,
            "unit_value": Decimal("1.000"),
        }
        defaults.update(overrides)
        tags = defaults.pop("tags", None)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        if tags is not None:
            product.tags.set(tags)
        if stock and stock > 0:
            record_manual_stock_in(
                product=product,
                store=store,
                quantity=stock,
                actor=None,
                reason="Test stock",
            )
            product.refresh_from_db()
        return product

    def attach_image(self, product, *, primary=True):
        buffer = BytesIO()
        Image.new("RGB", (40, 40), (10, 20, 30)).save(buffer, format="JPEG")
        buffer.seek(0)
        from django.core.files.uploadedfile import SimpleUploadedFile

        image = ProductImage(
            product=product,
            image=SimpleUploadedFile(
                "photo.jpg", buffer.read(), content_type="image/jpeg"
            ),
            is_primary=primary,
            alt_text=f"{product.name} photo",
        )
        image.full_clean()
        image.save()
        return image

    def create_customer(self, username="shopper"):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="secure-password-123",
            role=Role.CUSTOMER,
        )
        customer = Customer(
            user=user,
            registration_source=RegistrationSource.WEBSITE,
        )
        customer.full_clean()
        customer.save()
        return customer


class PublicVisibilityQuerysetTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.product = self.create_public_product(name="Visible Juice")

    def test_approved_active_in_stock_product_is_public(self):
        self.assertIn(self.product, public_products_queryset())

    def test_pending_status_hidden(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status", "updated_at"])
        self.assertNotIn(self.product, public_products_queryset())

    def test_inactive_product_hidden(self):
        self.product.is_active = False
        self.product.save(update_fields=["is_active", "updated_at"])
        self.assertNotIn(self.product, public_products_queryset())

    def test_zero_final_price_hidden(self):
        Product.objects.filter(pk=self.product.pk).update(final_price=Decimal("0.00"))
        self.product.refresh_from_db()
        self.assertNotIn(self.product, public_products_queryset())

    def test_suspended_store_hidden(self):
        self.product.store.status = StoreStatus.SUSPENDED
        self.product.store.save(update_fields=["status", "updated_at"])
        self.assertNotIn(self.product, public_products_queryset())

    def test_inactive_store_flag_hidden(self):
        self.product.store.is_active = False
        self.product.store.save(update_fields=["is_active", "updated_at"])
        self.assertNotIn(self.product, public_products_queryset())

    def test_inactive_category_hidden(self):
        self.product.category.is_active = False
        self.product.category.save(update_fields=["is_active", "updated_at"])
        self.assertNotIn(self.product, public_products_queryset())

    def test_expired_product_hidden(self):
        self.product.expiry_date = timezone.localdate() - timedelta(days=1)
        self.product.save(update_fields=["expiry_date", "updated_at"])
        self.assertNotIn(self.product, public_products_queryset())

    def test_out_of_stock_hidden(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=Decimal("0"))
        self.product.refresh_from_db()
        self.assertNotIn(self.product, public_products_queryset())

    def test_future_expiry_still_visible(self):
        self.product.expiry_date = timezone.localdate() + timedelta(days=10)
        self.product.save(update_fields=["expiry_date", "updated_at"])
        self.assertIn(self.product, public_products_queryset())




class PublicCatalogueSecurityTests(PublicCatalogueTestMixin, TestCase):
    def setUp(self):
        self.product = self.create_public_product(
            name="Secure Item",
            store_price=Decimal("77.77"),
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("12.34"),
        )
        self.product.store.commission_percentage = Decimal("9.99")
        self.product.store.save(update_fields=["commission_percentage", "updated_at"])


    def test_public_card_excludes_sensitive_keys(self):
        card = public_product_card(
            public_products_queryset().get(pk=self.product.pk)
        )
        for key in ("store_price", "profit_margin", "profit_margin_type", "commission"):
            self.assertNotIn(key, card)


