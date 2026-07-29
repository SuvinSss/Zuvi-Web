from decimal import Decimal
from datetime import date
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from PIL import Image

from accounts.models import AdminAuditLog, Role
from locations.models import Address
from stores.models import Store, StoreCategory, StoreStatus, StoreType, StoreUser

from .models import (
    Brand,
    Product,
    ProductCategory,
    ProductPriceHistory,
    ProductStatus,
    ProductStatusHistory,
    ProductUnit,
    Tag,
)
from .pricing import (
    DiscountType,
    MarginType,
    calculate_final_price,
    calculate_prices,
    calculate_selling_price,
)
from .services import (
    add_product_image,
    apply_admin_pricing,
    changes_require_reapproval,
    create_product,
    delete_product_image,
    generate_product_code,
    record_product_status_change,
    set_primary_product_image,
    update_product,
)
from .status import (
    is_transition_allowed,
    permission_for_transition,
    product_is_publicly_available,
    validate_product_for_approval,
    validate_status_transition,
)
from .validators import (
    MAX_IMAGES_PER_PRODUCT,
    MAX_PRODUCT_IMAGE_SIZE_BYTES,
    product_image_upload_to,
    validate_product_image,
)

User = get_user_model()


class CatalogTestMixin:
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

    def create_store_category(self, name="Grocery", **overrides):
        defaults = {"name": name}
        defaults.update(overrides)
        return StoreCategory.objects.create(**defaults)

    def create_store(self, **overrides):
        category_name = overrides.pop(
            "category_name", f"StoreCat-{Address.objects.count() + 1}"
        )
        if "address" not in overrides:
            overrides["address"] = self.create_address()
        if "category" not in overrides:
            overrides["category"] = self.create_store_category(name=category_name)
        defaults = {
            "name": "Zoop Mart",
            "store_type": StoreType.OWN_STORE,
            "status": StoreStatus.ACTIVE,
            "is_active": True,
            "commission_percentage": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Store.objects.create(**defaults)

    def create_product_category(self, name="Electronics", **overrides):
        defaults = {"name": name}
        defaults.update(overrides)
        return ProductCategory.objects.create(**defaults)

    def create_brand(self, name="Acme", **overrides):
        defaults = {"name": name}
        defaults.update(overrides)
        return Brand.objects.create(**defaults)

    def create_tag(self, name="sale", **overrides):
        defaults = {"name": name}
        defaults.update(overrides)
        return Tag.objects.create(**defaults)

    def create_store_user(self, store, username="store-user", **overrides):
        defaults = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "secure-password-123",
            "role": Role.STORE_USER,
        }
        defaults.update(overrides)
        user = User.objects.create_user(**defaults)
        StoreUser.objects.create(store=store, user=user, is_primary=True, is_active=True)
        return user

    def create_product(self, store=None, **overrides):
        if store is None:
            store = self.create_store()
        if "category" not in overrides:
            overrides["category"] = self.create_product_category(
                name=f"Cat-{ProductCategory.objects.count() + 1}"
            )
        defaults = {
            "store": store,
            "name": "Sample Product",
            "sku": f"SKU-{Product.objects.count() + 1}",
            "store_price": Decimal("100.00"),
            "status": ProductStatus.PENDING,
        }
        defaults.update(overrides)
        tags = defaults.pop("tags", None)
        product = Product(**defaults)
        product.full_clean()
        product.save()
        if tags is not None:
            product.tags.set(tags)
        return product

    def _jpeg_bytes(self, size=(40, 40), color=(10, 20, 30)):
        buffer = BytesIO()
        Image.new("RGB", size, color).save(buffer, format="JPEG")
        return buffer.getvalue()

    def _png_bytes(self, size=(40, 40), color=(10, 20, 30)):
        buffer = BytesIO()
        Image.new("RGB", size, color).save(buffer, format="PNG")
        return buffer.getvalue()

    def _webp_bytes(self, size=(40, 40), color=(10, 20, 30)):
        buffer = BytesIO()
        Image.new("RGB", size, color).save(buffer, format="WEBP")
        return buffer.getvalue()

    def _uploaded_image(self, name="photo.jpg", content=None, content_type=None):
        if content is None:
            content = self._jpeg_bytes()
        if content_type is None:
            lowered = name.lower()
            if lowered.endswith(".png"):
                content_type = "image/png"
            elif lowered.endswith(".webp"):
                content_type = "image/webp"
            else:
                content_type = "image/jpeg"
        return SimpleUploadedFile(name, content, content_type=content_type)

    def grant_catalog_perms(self, user, *codenames):
        for codename in codenames:
            user.user_permissions.add(
                Permission.objects.get(
                    codename=codename,
                    content_type__app_label="catalog",
                )
            )

    def attach_product_image(self, product, *, primary=True):
        return add_product_image(
            product=product,
            image=self._uploaded_image(),
            alt_text="Test image",
            is_primary=primary,
        )

    def prepare_product_for_approval(self, product, *, priced_by):
        """Apply complete pricing and attach an image so approval can succeed."""
        apply_admin_pricing(
            product=product,
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("10.00"),
            changed_by=priced_by,
        )
        product.refresh_from_db()
        if not product.images.exists():
            self.attach_product_image(product)
        product.refresh_from_db()
        return product


class ProductCategoryModelTests(CatalogTestMixin, TestCase):
    def test_slug_generated_and_hierarchy(self):
        parent = self.create_product_category(name="Parent Cat")
        child = self.create_product_category(name="Child Cat", parent=parent)
        self.assertEqual(parent.slug, "parent-cat")
        self.assertEqual(str(child), "Parent Cat / Child Cat")

    def test_self_parent_rejected(self):
        category = self.create_product_category(name="Solo")
        category.parent = category
        with self.assertRaises(ValidationError):
            category.full_clean()

    def test_cycle_rejected(self):
        a = self.create_product_category(name="A")
        b = self.create_product_category(name="B", parent=a)
        a.parent = b
        with self.assertRaises(ValidationError):
            a.full_clean()


class ProductModelTests(CatalogTestMixin, TestCase):
    def test_product_code_generated(self):
        product = self.create_product()
        self.assertTrue(product.product_code.startswith("PR"))
        self.assertEqual(len(product.product_code), 10)

    def test_slug_unique_per_store_not_globally(self):
        store_a = self.create_store(name="Store A", category_name="A")
        store_b = self.create_store(name="Store B", category_name="B")
        cat = self.create_product_category(name="SlugCat")
        first = self.create_product(
            store=store_a, category=cat, sku="S1", name="Same Name", slug="same-name"
        )
        second = self.create_product(
            store=store_b, category=cat, sku="S2", name="Same Name", slug="same-name"
        )
        self.assertEqual(first.slug, "same-name")
        self.assertEqual(second.slug, "same-name")
        with self.assertRaises(ValidationError):
            duplicate = Product(
                store=store_a,
                name="Other",
                slug="same-name",
                sku="S3",
                category=cat,
                store_price=Decimal("10.00"),
            )
            duplicate.full_clean()

    def test_slug_auto_generated_from_name(self):
        product = self.create_product(name="Fresh Mango Juice", sku="MANGO-1")
        self.assertEqual(product.slug, "fresh-mango-juice")

    def test_sku_unique_per_store_not_globally(self):
        store_a = self.create_store(name="Store A", category_name="A")
        store_b = self.create_store(name="Store B", category_name="B")
        cat = self.create_product_category(name="Shared")
        self.create_product(store=store_a, sku="SAME", category=cat)
        other = self.create_product(store=store_b, sku="SAME", category=cat, name="Other")
        self.assertEqual(other.sku, "SAME")
        with self.assertRaises(ValidationError):
            duplicate = Product(
                store=store_a,
                name="Dup",
                sku="SAME",
                category=cat,
                store_price=Decimal("10.00"),
            )
            duplicate.full_clean()

    def test_store_price_negative_rejected(self):
        store = self.create_store()
        product = Product(
            store=store,
            name="Bad",
            sku="BAD",
            category=self.create_product_category(name="BadCat"),
            store_price=Decimal("-1.00"),
        )
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_stock_quantity_negative_rejected(self):
        store = self.create_store()
        product = Product(
            store=store,
            name="Bad Qty",
            sku="BAD-Q",
            category=self.create_product_category(name="BadQtyCat"),
            store_price=Decimal("10.00"),
            stock_quantity=Decimal("-0.001"),
        )
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_manufacturing_date_cannot_be_future(self):
        from datetime import timedelta

        from django.utils import timezone

        store = self.create_store()
        product = Product(
            store=store,
            name="Future Mfg",
            sku="FUT-1",
            category=self.create_product_category(name="DateCat"),
            store_price=Decimal("10.00"),
            manufacturing_date=timezone.localdate() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError) as ctx:
            product.full_clean()
        self.assertIn("manufacturing_date", ctx.exception.message_dict)

    def test_expiry_before_manufacturing_rejected(self):
        from datetime import date

        store = self.create_store()
        product = Product(
            store=store,
            name="Expired Logic",
            sku="EXP-1",
            category=self.create_product_category(name="ExpCat"),
            store_price=Decimal("10.00"),
            manufacturing_date=date(2025, 6, 1),
            expiry_date=date(2025, 5, 1),
        )
        with self.assertRaises(ValidationError) as ctx:
            product.full_clean()
        self.assertIn("expiry_date", ctx.exception.message_dict)

    def test_computed_prices_ignored_from_caller(self):
        product = self.create_product(store_price=Decimal("100.00"))
        product.profit_margin_type = MarginType.FIXED
        product.profit_margin = Decimal("10.00")
        product.selling_price = Decimal("1.00")
        product.final_price = Decimal("1.00")
        product.full_clean()
        self.assertEqual(product.selling_price, Decimal("110.00"))
        self.assertEqual(product.final_price, Decimal("110.00"))

    def test_prices_use_decimal_fields(self):
        product = self.create_product()
        for field_name in (
            "store_price",
            "profit_margin",
            "selling_price",
            "discount_value",
            "final_price",
            "stock_quantity",
        ):
            field = Product._meta.get_field(field_name)
            self.assertEqual(field.get_internal_type(), "DecimalField")

    def test_unit_choices_are_text_choices(self):
        from catalog.models import ProductUnit

        product = self.create_product(unit=ProductUnit.KG)
        self.assertEqual(product.unit, ProductUnit.KG)
        self.assertEqual(product.get_unit_display(), "Kilogram")


class PricingCalculationTests(TestCase):
    def test_fixed_margin_and_percentage_discount(self):
        selling, final = calculate_prices(
            store_price=Decimal("100.00"),
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("20.00"),
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal("10.00"),
        )
        self.assertEqual(selling, Decimal("120.00"))
        self.assertEqual(final, Decimal("108.00"))

    def test_percentage_margin_and_fixed_discount(self):
        selling, final = calculate_prices(
            store_price=Decimal("200.00"),
            profit_margin_type=MarginType.PERCENTAGE,
            profit_margin=Decimal("10.00"),
            discount_type=DiscountType.FIXED,
            discount_value=Decimal("5.00"),
        )
        self.assertEqual(selling, Decimal("220.00"))
        self.assertEqual(final, Decimal("215.00"))

    def test_no_discount_equals_selling(self):
        selling, final = calculate_prices(
            store_price=Decimal("50.00"),
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("5.00"),
        )
        self.assertEqual(selling, final)

    def test_fixed_discount_cannot_exceed_selling(self):
        with self.assertRaises(ValidationError):
            calculate_final_price(
                selling_price=Decimal("10.00"),
                discount_type=DiscountType.FIXED,
                discount_value=Decimal("11.00"),
            )

    def test_percentage_margin_over_100_rejected(self):
        with self.assertRaises(ValidationError):
            calculate_selling_price(
                store_price=Decimal("10.00"),
                profit_margin_type=MarginType.PERCENTAGE,
                profit_margin=Decimal("101.00"),
            )

    def test_apply_calculated_prices_clears_without_margin(self):
        from catalog.pricing import apply_calculated_prices

        product = Product(
            store_price=Decimal("10.00"),
            selling_price=Decimal("99.00"),
            final_price=Decimal("99.00"),
        )
        apply_calculated_prices(product)
        self.assertIsNone(product.selling_price)
        self.assertIsNone(product.final_price)

    def test_quantize_half_up(self):
        selling, final = calculate_prices(
            store_price=Decimal("10.00"),
            profit_margin_type=MarginType.PERCENTAGE,
            profit_margin=Decimal("33.33"),
        )
        # 10 * 1.3333 = 13.333 → 13.33
        self.assertEqual(selling, Decimal("13.33"))
        self.assertEqual(final, Decimal("13.33"))


class ProductPricingWorkflowTests(CatalogTestMixin, TestCase):
    """Management /management/products/<pk>/pricing/ workflow."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="price-admin",
            email="price-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.grant_catalog_perms(
            self.admin, "view_product", "manage_product_pricing"
        )
        self.store = self.create_store()
        self.category = self.create_product_category(name="PriceCat")
        self.product = self.create_product(
            store=self.store,
            category=self.category,
            sku="PRICE-1",
            name="Priced Product",
            store_price=Decimal("100.00"),
            status=ProductStatus.PENDING,
        )
        self.url = reverse(
            "catalog:product_pricing", kwargs={"pk": self.product.pk}
        )

    def test_url_shape(self):
        self.assertEqual(self.url, f"/management/products/{self.product.pk}/pricing/")

    def test_fixed_margin_and_fixed_discount_via_portal(self):
        self.client.login(username="price-admin", password="secure-password-123")
        response = self.client.post(
            self.url,
            {
                "profit_margin_type": MarginType.FIXED,
                "profit_margin": "25.00",
                "discount_type": DiscountType.FIXED,
                "discount_value": "10.00",
                "reason": "Launch pricing",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.selling_price, Decimal("125.00"))
        self.assertEqual(self.product.final_price, Decimal("115.00"))
        history = ProductPriceHistory.objects.filter(product=self.product).latest(
            "created_at"
        )
        self.assertEqual(history.selling_price, Decimal("125.00"))
        self.assertEqual(history.final_price, Decimal("115.00"))
        self.assertEqual(history.reason, "Launch pricing")

    def test_percentage_margin_and_percentage_discount_via_portal(self):
        self.client.login(username="price-admin", password="secure-password-123")
        response = self.client.post(
            self.url,
            {
                "profit_margin_type": MarginType.PERCENTAGE,
                "profit_margin": "20.00",
                "discount_type": DiscountType.PERCENTAGE,
                "discount_value": "10.00",
                "reason": "Promo",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.selling_price, Decimal("120.00"))
        self.assertEqual(self.product.final_price, Decimal("108.00"))

    def test_manipulated_post_selling_and_final_are_ignored(self):
        self.client.login(username="price-admin", password="secure-password-123")
        response = self.client.post(
            self.url,
            {
                "profit_margin_type": MarginType.FIXED,
                "profit_margin": "10.00",
                "discount_type": DiscountType.PERCENTAGE,
                "discount_value": "5.00",
                "selling_price": "0.01",
                "final_price": "0.01",
                "store_price": "1.00",
                "reason": "Tamper attempt",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.store_price, Decimal("100.00"))
        self.assertEqual(self.product.selling_price, Decimal("110.00"))
        self.assertEqual(self.product.final_price, Decimal("104.50"))

    def test_negative_margin_rejected(self):
        self.client.login(username="price-admin", password="secure-password-123")
        response = self.client.post(
            self.url,
            {
                "profit_margin_type": MarginType.FIXED,
                "profit_margin": "-5.00",
                "discount_type": "",
                "discount_value": "0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertIsNone(self.product.selling_price)

    def test_percentage_discount_over_100_rejected(self):
        self.client.login(username="price-admin", password="secure-password-123")
        response = self.client.post(
            self.url,
            {
                "profit_margin_type": MarginType.FIXED,
                "profit_margin": "10.00",
                "discount_type": DiscountType.PERCENTAGE,
                "discount_value": "101.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "between 0 and 100")
        self.product.refresh_from_db()
        self.assertIsNone(self.product.final_price)

    def test_fixed_discount_exceeding_selling_rejected(self):
        self.client.login(username="price-admin", password="secure-password-123")
        response = self.client.post(
            self.url,
            {
                "profit_margin_type": MarginType.FIXED,
                "profit_margin": "5.00",
                "discount_type": DiscountType.FIXED,
                "discount_value": "200.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot exceed the selling price")

    def test_no_duplicate_price_history_when_unchanged(self):
        self.client.login(username="price-admin", password="secure-password-123")
        payload = {
            "profit_margin_type": MarginType.FIXED,
            "profit_margin": "12.00",
            "discount_type": "",
            "discount_value": "0",
            "reason": "Initial",
        }
        self.assertEqual(self.client.post(self.url, payload).status_code, 302)
        count_after_first = ProductPriceHistory.objects.filter(
            product=self.product
        ).count()
        payload["reason"] = "Same values again"
        self.assertEqual(self.client.post(self.url, payload).status_code, 302)
        self.assertEqual(
            ProductPriceHistory.objects.filter(product=self.product).count(),
            count_after_first,
        )

    def test_apply_admin_pricing_service_fixed_and_percentage(self):
        apply_admin_pricing(
            product=self.product,
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("15.55"),
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal("2.50"),
            changed_by=self.admin,
            reason="Service path",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.selling_price, Decimal("115.55"))
        self.assertEqual(self.product.final_price, Decimal("112.66"))

        apply_admin_pricing(
            product=self.product,
            profit_margin_type=MarginType.PERCENTAGE,
            profit_margin=Decimal("12.50"),
            discount_type=DiscountType.FIXED,
            discount_value=Decimal("3.25"),
            changed_by=self.admin,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.selling_price, Decimal("112.50"))
        self.assertEqual(self.product.final_price, Decimal("109.25"))


class ProductStatusTests(CatalogTestMixin, TestCase):
    def test_reject_requires_reason(self):
        product = self.create_product(status=ProductStatus.PENDING)
        with self.assertRaises(ValidationError):
            validate_status_transition(
                current_status=product.status,
                new_status=ProductStatus.REJECTED,
                reason="",
                product=product,
            )

    def test_approve_requires_pricing(self):
        product = self.create_product(status=ProductStatus.PENDING)
        self.attach_product_image(product)
        with self.assertRaises(ValidationError) as ctx:
            validate_status_transition(
                current_status=product.status,
                new_status=ProductStatus.APPROVED,
                product=product,
            )
        self.assertTrue(
            any("pricing" in str(msg).lower() for msg in ctx.exception.messages)
        )

    def test_store_user_cannot_approve(self):
        product = self.create_product(status=ProductStatus.PENDING)
        admin = User.objects.create_user(
            username="pricer",
            email="pricer@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.prepare_product_for_approval(product, priced_by=admin)
        with self.assertRaises(ValidationError):
            validate_status_transition(
                current_status=product.status,
                new_status=ProductStatus.APPROVED,
                product=product,
                actor_is_store_user=True,
            )


class ProductApprovalRejectionTests(CatalogTestMixin, TestCase):
    """Valid / invalid approval and rejection transitions."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="approve-admin",
            email="approve-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.grant_catalog_perms(
            self.admin,
            "view_product",
            "change_product",
            "approve_product",
            "manage_product_pricing",
        )
        self.store = self.create_store()
        self.category = self.create_product_category(name="ApproveCat")
        self.product = self.create_product(
            store=self.store,
            category=self.category,
            sku="APR-1",
            name="Approval Product",
            store_price=Decimal("50.00"),
            status=ProductStatus.DRAFT,
        )
        self.status_url = reverse(
            "catalog:product_change_status", kwargs={"pk": self.product.pk}
        )

    def test_allowed_transition_matrix(self):
        self.assertTrue(
            is_transition_allowed(ProductStatus.DRAFT, ProductStatus.PENDING)
        )
        self.assertTrue(
            is_transition_allowed(ProductStatus.PENDING, ProductStatus.APPROVED)
        )
        self.assertTrue(
            is_transition_allowed(ProductStatus.PENDING, ProductStatus.REJECTED)
        )
        self.assertTrue(
            is_transition_allowed(ProductStatus.REJECTED, ProductStatus.PENDING)
        )
        self.assertTrue(
            is_transition_allowed(ProductStatus.APPROVED, ProductStatus.INACTIVE)
        )
        self.assertTrue(
            is_transition_allowed(ProductStatus.INACTIVE, ProductStatus.PENDING)
        )
        self.assertTrue(
            is_transition_allowed(ProductStatus.INACTIVE, ProductStatus.APPROVED)
        )
        self.assertFalse(
            is_transition_allowed(ProductStatus.DRAFT, ProductStatus.APPROVED)
        )
        self.assertFalse(
            is_transition_allowed(ProductStatus.APPROVED, ProductStatus.REJECTED)
        )

    def test_permission_mapping(self):
        self.assertEqual(
            permission_for_transition(ProductStatus.PENDING, ProductStatus.APPROVED),
            "catalog.approve_product",
        )
        self.assertEqual(
            permission_for_transition(ProductStatus.PENDING, ProductStatus.REJECTED),
            "catalog.approve_product",
        )
        self.assertEqual(
            permission_for_transition(ProductStatus.APPROVED, ProductStatus.INACTIVE),
            "catalog.change_product",
        )
        self.assertEqual(
            permission_for_transition(ProductStatus.INACTIVE, ProductStatus.PENDING),
            "catalog.change_product",
        )
        self.assertEqual(
            permission_for_transition(ProductStatus.INACTIVE, ProductStatus.APPROVED),
            "catalog.approve_product",
        )
        self.assertEqual(
            permission_for_transition(ProductStatus.DRAFT, ProductStatus.PENDING),
            "catalog.change_product",
        )

    def test_draft_to_pending_by_store_user(self):
        store_user = self.create_store_user(self.store, username="submitter")
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.PENDING,
            changed_by=store_user,
            reason="Submitted for approval",
            actor_is_store_user=True,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)
        self.assertTrue(
            ProductStatusHistory.objects.filter(
                product=self.product,
                old_status=ProductStatus.DRAFT,
                new_status=ProductStatus.PENDING,
            ).exists()
        )

    def test_draft_to_pending_by_management(self):
        self.client.login(username="approve-admin", password="secure-password-123")
        response = self.client.post(
            self.status_url,
            {"new_status": ProductStatus.PENDING, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)

    def test_pending_to_approved_sets_metadata_and_history(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
            reason="Looks good",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.approved_by_id, self.admin.pk)
        self.assertIsNotNone(self.product.approved_at)
        self.assertEqual(self.product.rejection_reason, "")
        self.assertTrue(
            ProductStatusHistory.objects.filter(
                product=self.product,
                old_status=ProductStatus.PENDING,
                new_status=ProductStatus.APPROVED,
                changed_by=self.admin,
            ).exists()
        )

    def test_pending_to_rejected_requires_reason_and_clears_approval(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            record_product_status_change(
                product=self.product,
                new_status=ProductStatus.REJECTED,
                changed_by=self.admin,
                reason="",
            )
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.REJECTED,
            changed_by=self.admin,
            reason="Missing brand details",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.REJECTED)
        self.assertEqual(self.product.rejection_reason, "Missing brand details")
        self.assertIsNone(self.product.approved_by)
        self.assertIsNone(self.product.approved_at)

    def test_rejected_to_pending_after_store_resubmission(self):
        self.product.status = ProductStatus.REJECTED
        self.product.rejection_reason = "Fix images"
        self.product.save(update_fields=["status", "rejection_reason"])
        store_user = self.create_store_user(self.store, username="resubmitter")
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.PENDING,
            changed_by=store_user,
            reason="Resubmitted after fixes",
            actor_is_store_user=True,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)

    def test_approved_to_inactive_and_reactivate(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
        )
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.INACTIVE,
            changed_by=self.admin,
            reason="Seasonal pause",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.INACTIVE)
        self.assertIsNone(self.product.approved_by)
        self.assertIsNone(self.product.approved_at)

        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.PENDING,
            changed_by=self.admin,
            reason="Re-queue for review",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)

        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
        )
        # From PENDING we already approved; also cover INACTIVE → APPROVED directly.
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.INACTIVE,
            changed_by=self.admin,
        )
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
            reason="Reactivate listing",
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.approved_by_id, self.admin.pk)

    def test_approve_rejects_inactive_store(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        self.store.is_active = False
        self.store.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            validate_product_for_approval(self.product)
        self.assertTrue(
            any("active store" in str(msg).lower() for msg in ctx.exception.messages)
        )

    def test_approve_rejects_non_active_store_status(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        self.store.status = StoreStatus.SUSPENDED
        self.store.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            validate_product_for_approval(self.product)
        self.assertTrue(
            any("store status" in str(msg).lower() for msg in ctx.exception.messages)
        )

    def test_approve_rejects_inactive_category(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        self.category.is_active = False
        self.category.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(ValidationError) as ctx:
            validate_product_for_approval(self.product)
        self.assertTrue(
            any("category" in str(msg).lower() for msg in ctx.exception.messages)
        )

    def test_approve_rejects_missing_image(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        apply_admin_pricing(
            product=self.product,
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("10.00"),
            changed_by=self.admin,
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_product_for_approval(self.product)
        self.assertTrue(
            any("image" in str(msg).lower() for msg in ctx.exception.messages)
        )

    def test_approve_rejects_zero_final_price(self):
        self.product.status = ProductStatus.PENDING
        self.product.store_price = Decimal("0.00")
        self.product.save(update_fields=["status", "store_price"])
        with self.assertRaises(ValidationError):
            apply_admin_pricing(
                product=self.product,
                profit_margin_type=MarginType.FIXED,
                profit_margin=Decimal("0.00"),
                changed_by=self.admin,
            )
        # Force a zero final past the pricing service to prove approval still blocks it.
        Product.objects.filter(pk=self.product.pk).update(
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("0.00"),
            selling_price=Decimal("0.00"),
            final_price=Decimal("0.00"),
        )
        self.product.refresh_from_db()
        self.attach_product_image(self.product)
        with self.assertRaises(ValidationError) as ctx:
            validate_product_for_approval(self.product)
        self.assertTrue(
            any("final price" in str(msg).lower() for msg in ctx.exception.messages)
        )

    def test_pricing_rejects_hundred_percent_discount(self):
        with self.assertRaises(ValidationError):
            apply_admin_pricing(
                product=self.product,
                profit_margin_type=MarginType.FIXED,
                profit_margin=Decimal("10.00"),
                discount_type=DiscountType.PERCENTAGE,
                discount_value=Decimal("100.00"),
                changed_by=self.admin,
            )

    def test_invalid_transition_draft_to_approved(self):
        with self.assertRaises(ValidationError):
            record_product_status_change(
                product=self.product,
                new_status=ProductStatus.APPROVED,
                changed_by=self.admin,
            )

    def test_status_change_post_only_via_portal(self):
        self.client.login(username="approve-admin", password="secure-password-123")
        self.assertEqual(self.client.get(self.status_url).status_code, 405)

    def test_portal_approve_and_reject_flows(self):
        self.product.status = ProductStatus.PENDING
        self.product.save(update_fields=["status"])
        self.prepare_product_for_approval(self.product, priced_by=self.admin)
        self.client.login(username="approve-admin", password="secure-password-123")
        response = self.client.post(
            self.status_url,
            {"new_status": ProductStatus.APPROVED, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.approved_by_id, self.admin.pk)

        # Move back to pending via commercial reapproval path is not available
        # from APPROVED→REJECTED; reject from PENDING instead.
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.INACTIVE,
            changed_by=self.admin,
        )
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.PENDING,
            changed_by=self.admin,
        )
        response = self.client.post(
            self.status_url,
            {"new_status": ProductStatus.REJECTED, "reason": "Incomplete description"},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.REJECTED)
        self.assertEqual(self.product.rejection_reason, "Incomplete description")


class ProductWorkflowServiceTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="workflow-admin",
            email="workflow-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store = self.create_store()
        self.category = self.create_product_category(name="Workflow")

    def test_create_defaults_and_histories(self):
        product = create_product(
            store=self.store,
            product_data={
                "name": "Created",
                "sku": "WF-1",
                "category": self.category,
                "store_price": Decimal("80.00"),
            },
            created_by=self.admin,
            initial_status=ProductStatus.PENDING,
        )
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertTrue(
            ProductStatusHistory.objects.filter(product=product).exists()
        )
        self.assertTrue(ProductPriceHistory.objects.filter(product=product).exists())
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.PRODUCT_CREATED
            ).exists()
        )

    def test_pricing_then_approve(self):
        product = create_product(
            store=self.store,
            product_data={
                "name": "Approve Me",
                "sku": "WF-2",
                "category": self.category,
                "store_price": Decimal("100.00"),
            },
            created_by=self.admin,
            initial_status=ProductStatus.PENDING,
        )
        apply_admin_pricing(
            product=product,
            profit_margin_type=MarginType.PERCENTAGE,
            profit_margin=Decimal("25.00"),
            discount_type=DiscountType.FIXED,
            discount_value=Decimal("10.00"),
            changed_by=self.admin,
        )
        product.refresh_from_db()
        self.assertEqual(product.selling_price, Decimal("125.00"))
        self.assertEqual(product.final_price, Decimal("115.00"))
        self.attach_product_image(product)
        record_product_status_change(
            product=product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
        )
        product.refresh_from_db()
        self.assertEqual(product.status, ProductStatus.APPROVED)
        self.assertEqual(product.approved_by_id, self.admin.pk)
        self.assertIsNotNone(product.approved_at)

    def test_store_edit_of_approved_returns_pending(self):
        product = create_product(
            store=self.store,
            product_data={
                "name": "Approved",
                "sku": "WF-3",
                "category": self.category,
                "store_price": Decimal("40.00"),
            },
            created_by=self.admin,
            initial_status=ProductStatus.PENDING,
        )
        apply_admin_pricing(
            product=product,
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("5.00"),
            changed_by=self.admin,
        )
        self.attach_product_image(product)
        record_product_status_change(
            product=product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
        )
        product.refresh_from_db()
        prior_selling = product.selling_price
        prior_final = product.final_price
        prior_margin = product.profit_margin
        store_user = self.create_store_user(self.store, username="editor")
        update_product(
            product=product,
            product_data={"store_price": Decimal("45.00"), "name": "Approved"},
            updated_by=store_user,
            actor_is_store_user=True,
        )
        product.refresh_from_db()
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertEqual(product.store_price, Decimal("45.00"))
        self.assertEqual(product.selling_price, prior_selling)
        self.assertEqual(product.final_price, prior_final)
        self.assertEqual(product.profit_margin, prior_margin)
        self.assertFalse(product_is_publicly_available(product))
        self.assertTrue(
            ProductStatusHistory.objects.filter(
                product=product,
                old_status=ProductStatus.APPROVED,
                new_status=ProductStatus.PENDING,
            ).exists()
        )


class ProductResubmissionTests(CatalogTestMixin, TestCase):
    """APPROVED → PENDING rules for catalogue edits vs inventory-only edits."""

    def setUp(self):
        self.store = self.create_store()
        self.category = self.create_product_category(name="Resub Cat")
        self.other_category = self.create_product_category(name="Other Cat")
        self.brand = self.create_brand(name="Resub Brand")
        self.other_brand = self.create_brand(name="Other Brand")
        self.admin = User.objects.create_user(
            username="resub-admin",
            email="resub-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.store_user = self.create_store_user(self.store, username="resub-editor")
        self.product = create_product(
            store=self.store,
            product_data={
                "name": "Resub Product",
                "sku": "RESUB-1",
                "category": self.category,
                "brand": self.brand,
                "description": "Original description",
                "unit": ProductUnit.PIECE,
                "unit_value": Decimal("1.000"),
                "store_price": Decimal("100.00"),
                "stock_quantity": Decimal("10.000"),
                "low_stock_threshold": Decimal("2.000"),
                "manufacturing_date": date(2025, 1, 1),
                "expiry_date": date(2027, 1, 1),
            },
            created_by=self.admin,
            initial_status=ProductStatus.PENDING,
        )
        apply_admin_pricing(
            product=self.product,
            profit_margin_type=MarginType.PERCENTAGE,
            profit_margin=Decimal("20.00"),
            discount_type=DiscountType.FIXED,
            discount_value=Decimal("5.00"),
            changed_by=self.admin,
        )
        self.attach_product_image(self.product)
        record_product_status_change(
            product=self.product,
            new_status=ProductStatus.APPROVED,
            changed_by=self.admin,
        )
        self.product.refresh_from_db()
        self.prior_selling = self.product.selling_price
        self.prior_final = self.product.final_price
        self.prior_margin_type = self.product.profit_margin_type
        self.prior_margin = self.product.profit_margin
        self.prior_discount_type = self.product.discount_type
        self.prior_discount = self.product.discount_value

    def _assert_returned_to_pending(self, *, expected_fields=None):
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)
        self.assertEqual(self.product.selling_price, self.prior_selling)
        self.assertEqual(self.product.final_price, self.prior_final)
        self.assertEqual(self.product.profit_margin_type, self.prior_margin_type)
        self.assertEqual(self.product.profit_margin, self.prior_margin)
        self.assertEqual(self.product.discount_type, self.prior_discount_type)
        self.assertEqual(self.product.discount_value, self.prior_discount)
        self.assertFalse(product_is_publicly_available(self.product))
        history = ProductStatusHistory.objects.filter(
            product=self.product,
            old_status=ProductStatus.APPROVED,
            new_status=ProductStatus.PENDING,
        ).latest("created_at")
        if expected_fields:
            for field in expected_fields:
                self.assertIn(field, history.reason)

    def _assert_stays_approved(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertTrue(product_is_publicly_available(self.product))
        self.assertFalse(
            ProductStatusHistory.objects.filter(
                product=self.product,
                old_status=ProductStatus.APPROVED,
                new_status=ProductStatus.PENDING,
            ).exists()
        )

    def _store_edit(self, **product_data):
        update_product(
            product=self.product,
            product_data=product_data,
            updated_by=self.store_user,
            actor_is_store_user=True,
        )

    def test_name_change_returns_pending(self):
        self._store_edit(name="Renamed Product")
        self._assert_returned_to_pending(expected_fields=["name"])
        self.assertEqual(self.product.name, "Renamed Product")

    def test_category_change_returns_pending(self):
        self._store_edit(category=self.other_category)
        self._assert_returned_to_pending(expected_fields=["category"])
        self.assertEqual(self.product.category_id, self.other_category.pk)

    def test_brand_change_returns_pending(self):
        self._store_edit(brand=self.other_brand)
        self._assert_returned_to_pending(expected_fields=["brand"])
        self.assertEqual(self.product.brand_id, self.other_brand.pk)

    def test_description_change_returns_pending(self):
        self._store_edit(description="Updated description")
        self._assert_returned_to_pending(expected_fields=["description"])
        self.assertEqual(self.product.description, "Updated description")

    def test_unit_change_returns_pending(self):
        self._store_edit(unit=ProductUnit.KG)
        self._assert_returned_to_pending(expected_fields=["unit"])
        self.assertEqual(self.product.unit, ProductUnit.KG)

    def test_unit_value_change_returns_pending(self):
        self._store_edit(unit_value=Decimal("2.500"))
        self._assert_returned_to_pending(expected_fields=["unit_value"])
        self.assertEqual(self.product.unit_value, Decimal("2.500"))

    def test_store_price_change_returns_pending_and_preserves_admin_pricing(self):
        self._store_edit(store_price=Decimal("130.00"))
        self._assert_returned_to_pending(expected_fields=["store_price"])
        self.assertEqual(self.product.store_price, Decimal("130.00"))
        # Recalculated would be 130 * 1.2 - 5 = 151; preserved final must stay 115.
        self.assertEqual(self.prior_final, Decimal("115.00"))
        self.assertEqual(self.product.final_price, Decimal("115.00"))
        self.assertTrue(
            ProductPriceHistory.objects.filter(
                product=self.product,
                store_price=Decimal("130.00"),
                final_price=Decimal("115.00"),
            ).exists()
        )

    def test_manufacturing_date_change_returns_pending(self):
        self._store_edit(manufacturing_date=date(2025, 6, 1))
        self._assert_returned_to_pending(expected_fields=["manufacturing_date"])
        self.assertEqual(self.product.manufacturing_date, date(2025, 6, 1))

    def test_expiry_date_change_returns_pending(self):
        self._store_edit(expiry_date=date(2028, 1, 1))
        self._assert_returned_to_pending(expected_fields=["expiry_date"])
        self.assertEqual(self.product.expiry_date, date(2028, 1, 1))

    def test_stock_quantity_alone_stays_approved(self):
        self._store_edit(stock_quantity=Decimal("25.000"))
        self._assert_stays_approved()
        self.assertEqual(self.product.stock_quantity, Decimal("25.000"))

    def test_low_stock_threshold_alone_stays_approved(self):
        self._store_edit(low_stock_threshold=Decimal("5.000"))
        self._assert_stays_approved()
        self.assertEqual(self.product.low_stock_threshold, Decimal("5.000"))

    def test_stock_and_threshold_together_stay_approved(self):
        self._store_edit(
            stock_quantity=Decimal("8.000"),
            low_stock_threshold=Decimal("4.000"),
        )
        self._assert_stays_approved()
        self.assertEqual(self.product.stock_quantity, Decimal("8.000"))
        self.assertEqual(self.product.low_stock_threshold, Decimal("4.000"))

    def test_unchanged_review_fields_do_not_force_pending(self):
        self.assertFalse(
            changes_require_reapproval(
                self.product,
                {
                    "name": self.product.name,
                    "category": self.product.category,
                    "brand": self.product.brand,
                    "description": self.product.description,
                    "unit": self.product.unit,
                    "unit_value": self.product.unit_value,
                    "store_price": self.product.store_price,
                    "manufacturing_date": self.product.manufacturing_date,
                    "expiry_date": self.product.expiry_date,
                },
            )
        )
        self._store_edit(
            name=self.product.name,
            store_price=self.product.store_price,
            stock_quantity=Decimal("11.000"),
        )
        self._assert_stays_approved()
        self.assertEqual(self.product.stock_quantity, Decimal("11.000"))

    def test_mixed_stock_and_name_change_returns_pending(self):
        self._store_edit(
            name="Mixed Edit",
            stock_quantity=Decimal("50.000"),
        )
        self._assert_returned_to_pending(expected_fields=["name"])
        self.assertEqual(self.product.stock_quantity, Decimal("50.000"))

    def test_pending_product_not_publicly_available(self):
        self.assertTrue(product_is_publicly_available(self.product))
        self._store_edit(name="Now Pending")
        self.product.refresh_from_db()
        self.assertFalse(product_is_publicly_available(self.product))
        self.product.is_active = False
        self.product.status = ProductStatus.APPROVED
        self.assertFalse(product_is_publicly_available(self.product))


class ProductImageValidationTests(CatalogTestMixin, TestCase):
    def test_valid_jpeg_accepted(self):
        validate_product_image(self._uploaded_image())

    def test_valid_png_and_webp_accepted(self):
        validate_product_image(
            self._uploaded_image(name="shot.png", content=self._png_bytes())
        )
        validate_product_image(
            self._uploaded_image(name="shot.webp", content=self._webp_bytes())
        )

    def test_oversized_rejected(self):
        content = self._jpeg_bytes() + (b"0" * (MAX_PRODUCT_IMAGE_SIZE_BYTES + 1))
        uploaded = SimpleUploadedFile("big.jpg", content, content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            validate_product_image(uploaded)

    def test_mismatched_extension_rejected(self):
        uploaded = self._uploaded_image(
            name="fake.png", content=self._jpeg_bytes()
        )
        with self.assertRaises(ValidationError):
            validate_product_image(uploaded)

    def test_non_image_content_rejected(self):
        uploaded = SimpleUploadedFile(
            "not-image.jpg", b"not-an-image", content_type="image/jpeg"
        )
        with self.assertRaises(ValidationError):
            validate_product_image(uploaded)

    def test_upload_path_uses_uuid(self):
        product = self.create_product()
        path = product_image_upload_to(product, "../../evil.jpg")
        self.assertTrue(path.startswith("products/images/"))
        self.assertTrue(path.endswith(".jpg"))
        self.assertNotIn("..", path)


class ProductImageManagementTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.store_a = self.create_store(name="Image Store A", category_name="ImgA")
        self.store_b = self.create_store(name="Image Store B", category_name="ImgB")
        self.category = self.create_product_category(name="ImgCat")
        self.product_a = self.create_product(
            store=self.store_a,
            category=self.category,
            sku="IMG-A",
            name="Image Product A",
        )
        self.product_b = self.create_product(
            store=self.store_b,
            category=self.category,
            sku="IMG-B",
            name="Image Product B",
        )
        self.admin = User.objects.create_user(
            username="img-admin",
            email="img-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.grant_catalog_perms(self.admin, "view_product", "change_product")
        self.store_user_a = self.create_store_user(
            self.store_a, username="img-store-a"
        )
        self.store_user_b = self.create_store_user(
            self.store_b, username="img-store-b"
        )

    def test_first_image_becomes_primary_automatically(self):
        image = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="one.jpg"),
            is_primary=False,
        )
        self.assertTrue(image.is_primary)
        self.assertEqual(self.product_a.images.filter(is_primary=True).count(), 1)

    def test_setting_primary_demotes_previous(self):
        first = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="one.jpg"),
        )
        second = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="two.jpg"),
            is_primary=True,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)
        set_primary_product_image(product=self.product_a, image_id=first.pk)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_primary)
        self.assertFalse(second.is_primary)
        self.assertEqual(self.product_a.images.filter(is_primary=True).count(), 1)

    def test_deleting_primary_promotes_next_image(self):
        first = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="one.jpg"),
            sort_order=1,
        )
        second = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="two.jpg"),
            sort_order=2,
        )
        third = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="three.jpg"),
            sort_order=3,
        )
        self.assertTrue(first.is_primary)
        delete_product_image(product=self.product_a, image_id=first.pk)
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertTrue(second.is_primary)
        self.assertFalse(third.is_primary)
        self.assertEqual(self.product_a.images.count(), 2)

    def test_max_five_images_enforced(self):
        for index in range(MAX_IMAGES_PER_PRODUCT):
            add_product_image(
                product=self.product_a,
                image=self._uploaded_image(name=f"img-{index}.jpg"),
            )
        with self.assertRaises(ValidationError):
            add_product_image(
                product=self.product_a,
                image=self._uploaded_image(name="overflow.jpg"),
            )
        self.assertEqual(self.product_a.images.count(), MAX_IMAGES_PER_PRODUCT)

    def test_management_upload_and_set_primary_via_portal(self):
        self.client.login(username="img-admin", password="secure-password-123")
        url = reverse("catalog:product_images", kwargs={"pk": self.product_a.pk})
        response = self.client.post(
            url,
            {
                "image": self._uploaded_image(name="mgmt.jpg"),
                "alt_text": "Front",
                "sort_order": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product_a.images.count(), 1)
        primary = self.product_a.images.get()
        self.assertTrue(primary.is_primary)

        second = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="second.jpg"),
        )
        response = self.client.post(
            reverse(
                "catalog:product_image_set_primary",
                kwargs={"pk": self.product_a.pk, "image_id": second.pk},
            )
        )
        self.assertEqual(response.status_code, 302)
        second.refresh_from_db()
        self.assertTrue(second.is_primary)

    def test_management_delete_requires_post(self):
        image = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="del.jpg"),
        )
        self.client.login(username="img-admin", password="secure-password-123")
        url = reverse(
            "catalog:product_image_delete",
            kwargs={"pk": self.product_a.pk, "image_id": image.pk},
        )
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(self.product_a.images.filter(pk=image.pk).exists())

    def test_cannot_delete_last_image_on_approved_product(self):
        image = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="only.jpg"),
        )
        self.product_a.status = ProductStatus.APPROVED
        self.product_a.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            delete_product_image(product=self.product_a, image_id=image.pk)
        self.assertTrue(self.product_a.images.filter(pk=image.pk).exists())

    def test_store_user_can_manage_own_store_images(self):
        self.client.login(username="img-store-a", password="secure-password-123")
        url = reverse(
            "catalog:store_product_images", kwargs={"pk": self.product_a.pk}
        )
        response = self.client.post(
            url,
            {"image": self._uploaded_image(name="store.jpg"), "alt_text": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.product_a.images.count(), 1)

    def test_store_user_cannot_manage_other_store_images(self):
        image = add_product_image(
            product=self.product_a,
            image=self._uploaded_image(name="owned.jpg"),
        )
        self.client.login(username="img-store-b", password="secure-password-123")
        self.assertEqual(
            self.client.get(
                reverse(
                    "catalog:store_product_images",
                    kwargs={"pk": self.product_a.pk},
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "catalog:store_product_image_delete",
                    kwargs={"pk": self.product_a.pk, "image_id": image.pk},
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "catalog:store_product_image_set_primary",
                    kwargs={"pk": self.product_a.pk, "image_id": image.pk},
                )
            ).status_code,
            404,
        )
        self.assertTrue(self.product_a.images.filter(pk=image.pk).exists())

    def test_management_images_require_change_permission(self):
        limited = User.objects.create_user(
            username="img-view-only",
            email="img-view-only@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.grant_catalog_perms(limited, "view_product")
        self.client.login(username="img-view-only", password="secure-password-123")
        url = reverse("catalog:product_images", kwargs={"pk": self.product_a.pk})
        self.assertEqual(self.client.get(url).status_code, 403)


class ProductCodeConcurrencyTests(CatalogTestMixin, TransactionTestCase):
    def test_generate_product_code_unique(self):
        codes = {generate_product_code() for _ in range(20)}
        self.assertEqual(len(codes), 20)

    def test_save_retries_when_code_collides(self):
        store = self.create_store()
        category = self.create_product_category(name="RetryCat")
        existing = Product(
            store=store,
            name="Existing",
            sku="EXIST-1",
            category=category,
            store_price=Decimal("1.00"),
            product_code="PRCOLLIDE1",
        )
        # Bypass allocation by setting code then calling Model.save directly.
        super(Product, existing).save()

        product = Product(
            store=store,
            name="Retry",
            sku="RETRY-1",
            category=category,
            store_price=Decimal("1.00"),
        )
        with mock.patch(
            "catalog.services.generate_product_code",
            side_effect=["PRCOLLIDE1", "PRUNIQUE99"],
        ):
            product.save()

        self.assertEqual(product.product_code, "PRUNIQUE99")
        self.assertTrue(Product.objects.filter(product_code="PRUNIQUE99").exists())


class ManagementProductPermissionTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.super_admin = User.objects.create_user(
            username="prod-super",
            email="prod-super@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.admin = User.objects.create_user(
            username="prod-admin",
            email="prod-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.store = self.create_store()
        self.category = self.create_product_category(name="PermCat")
        self.brand = self.create_brand(name="PermBrand")
        self.product = self.create_product(
            store=self.store,
            category=self.category,
            brand=self.brand,
            sku="PERM-1",
            name="Permission Product",
            stock_quantity=Decimal("5.000"),
            is_active=True,
        )

    def test_admin_without_perm_gets_403(self):
        self.client.login(username="prod-admin", password="secure-password-123")
        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_with_view_can_list(self):
        self.grant_catalog_perms(self.admin, "view_product")
        self.client.login(username="prod-admin", password="secure-password-123")
        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)

    def test_product_list_avoids_n_plus_one_for_related_fields(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for index in range(8):
            self.create_product(
                store=self.store,
                category=self.category,
                brand=self.brand,
                sku=f"N1-{index}",
                name=f"N+1 Product {index}",
            )
        self.client.login(username="prod-super", password="secure-password-123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.context["page_obj"]), 9)
        # Prefetch/select_related should keep query count stable vs product count.
        self.assertLessEqual(len(ctx.captured_queries), 20)

    def test_super_admin_can_list(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_search_and_filters(self):
        other = self.create_product(
            store=self.store,
            category=self.category,
            sku="OTHER-1",
            name="Other Item",
            stock_quantity=Decimal("0"),
            is_active=False,
        )
        self.client.login(username="prod-super", password="secure-password-123")
        by_brand = self.client.get(
            reverse("catalog:product_list"), {"q": "PermBrand"}
        )
        self.assertContains(by_brand, "Permission Product")
        self.assertNotContains(by_brand, "Other Item")

        out_of_stock = self.client.get(
            reverse("catalog:product_list"), {"stock": "out_of_stock"}
        )
        self.assertContains(out_of_stock, "Other Item")
        self.assertNotContains(out_of_stock, "Permission Product")

        inactive = self.client.get(
            reverse("catalog:product_list"), {"is_active": "false"}
        )
        self.assertContains(inactive, "Other Item")
        self.assertNotContains(inactive, "Permission Product")
        self.assertEqual(other.is_active, False)

    def test_list_columns_present(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.get(reverse("catalog:product_list"))
        for label in (
            "Code",
            "SKU",
            "Name",
            "Store",
            "Category",
            "Brand",
            "Store price",
            "Final price",
            "Stock",
            "Status",
            "Active",
            "Created",
        ):
            self.assertContains(response, label)

    def test_detail_sections_present(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.get(
            reverse("catalog:product_detail", kwargs={"pk": self.product.pk})
        )
        self.assertEqual(response.status_code, 200)
        for section in (
            "General information",
            "Store information",
            "Pricing breakdown",
            "Images",
            "Dates",
            "Approval information",
            "Status history",
            "Price history",
        ):
            self.assertContains(response, section)

    def test_pricing_requires_manage_product_pricing(self):
        self.grant_catalog_perms(self.admin, "view_product")
        self.client.login(username="prod-admin", password="secure-password-123")
        url = reverse("catalog:product_pricing", kwargs={"pk": self.product.pk})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant_catalog_perms(self.admin, "manage_product_pricing")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_pricing_ignores_submitted_final_price(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:product_pricing", kwargs={"pk": self.product.pk}),
            {
                "profit_margin_type": MarginType.FIXED,
                "profit_margin": "15.00",
                "discount_type": "",
                "discount_value": "0",
                "final_price": "1.00",
                "selling_price": "1.00",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.selling_price, Decimal("115.00"))
        self.assertEqual(self.product.final_price, Decimal("115.00"))
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.PRODUCT_PRICING_CHANGED
            ).exists()
        )

    def test_pricing_page_shows_readonly_store_price_and_previews(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.get(
            reverse("catalog:product_pricing", kwargs={"pk": self.product.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Store price")
        self.assertContains(response, "Calculated selling price preview")
        self.assertContains(response, "Calculated final price preview")
        self.assertContains(response, "Change reason")
        self.assertContains(response, str(self.product.store_price))
        self.assertContains(response, 'id="id_store_price_display"')
        self.assertContains(response, "readonly")

    def test_status_change_is_post_only(self):
        self.client.login(username="prod-super", password="secure-password-123")
        url = reverse("catalog:product_change_status", kwargs={"pk": self.product.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_reject_requires_reason(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:product_change_status", kwargs={"pk": self.product.pk}),
            {"new_status": ProductStatus.REJECTED, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.PENDING)

    def test_approve_flow_via_portal(self):
        self.client.login(username="prod-super", password="secure-password-123")
        self.prepare_product_for_approval(self.product, priced_by=self.super_admin)
        response = self.client.post(
            reverse("catalog:product_change_status", kwargs={"pk": self.product.pk}),
            {"new_status": ProductStatus.APPROVED, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, ProductStatus.APPROVED)
        self.assertEqual(self.product.approved_by.username, "prod-super")
        self.assertIsNotNone(self.product.approved_at)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.PRODUCT_STATUS_CHANGED
            ).exists()
        )

    def test_images_page_requires_change_permission(self):
        self.grant_catalog_perms(self.admin, "view_product")
        self.client.login(username="prod-admin", password="secure-password-123")
        url = reverse("catalog:product_images", kwargs={"pk": self.product.pk})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.grant_catalog_perms(self.admin, "change_product")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_image_delete_is_post_only(self):
        self.client.login(username="prod-super", password="secure-password-123")
        url = reverse(
            "catalog:product_image_delete",
            kwargs={"pk": self.product.pk, "image_id": 1},
        )
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_taxonomy_urls(self):
        self.client.login(username="prod-super", password="secure-password-123")
        self.assertEqual(
            self.client.get(reverse("catalog:category_list")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("catalog:brand_list")).status_code, 200
        )
        self.assertEqual(self.client.get(reverse("catalog:tag_list")).status_code, 200)
        self.assertEqual(
            reverse("catalog:category_list"), "/management/product-categories/"
        )
        self.assertEqual(reverse("catalog:brand_list"), "/management/brands/")
        self.assertEqual(reverse("catalog:tag_list"), "/management/tags/")
        self.assertEqual(
            reverse("catalog:product_images", kwargs={"pk": self.product.pk}),
            f"/management/products/{self.product.pk}/images/",
        )

    def test_create_product_logs_audit(self):
        self.client.login(username="prod-super", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:product_create"),
            {
                "store": self.store.pk,
                "name": "Created Via Portal",
                "sku": "CREATE-1",
                "category": self.category.pk,
                "brand": self.brand.pk,
                "store_price": "25.00",
                "unit": "PIECE",
                "stock_quantity": "2",
                "is_active": "on",
                "description": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(sku="CREATE-1")
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.PRODUCT_CREATED,
                metadata__product_code=product.product_code,
            ).exists()
        )

    def test_django_admin_status_and_prices_readonly(self):
        from catalog.admin import ProductAdmin

        self.assertIn("status", ProductAdmin.readonly_fields)
        self.assertIn("selling_price", ProductAdmin.readonly_fields)
        self.assertIn("final_price", ProductAdmin.readonly_fields)
        self.assertIn("product_code", ProductAdmin.readonly_fields)


class StorePortalProductIsolationTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.store_a = self.create_store(name="Store A", category_name="SA")
        self.store_b = self.create_store(name="Store B", category_name="SB")
        self.user_a = self.create_store_user(self.store_a, username="portal-a")
        self.user_b = self.create_store_user(self.store_b, username="portal-b")
        self.cat = self.create_product_category(name="IsoCat")
        self.brand = self.create_brand(name="IsoBrand")
        self.product_a = self.create_product(
            store=self.store_a,
            category=self.cat,
            brand=self.brand,
            sku="ISO-A",
            name="A Product",
            stock_quantity=Decimal("10.000"),
            low_stock_threshold=Decimal("3.000"),
        )
        self.product_b = self.create_product(
            store=self.store_b,
            category=self.cat,
            brand=self.brand,
            sku="ISO-B",
            name="B Product",
        )

    def test_list_only_own_store_products(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.get(reverse("catalog:store_product_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("A Product", content)
        self.assertNotIn("B Product", content)
        self.assertContains(response, "Final price")
        self.assertContains(response, "Rejection")

    def test_list_filters_category_brand_stock(self):
        self.create_product(
            store=self.store_a,
            category=self.cat,
            sku="ZERO",
            name="Zero Stock",
            stock_quantity=Decimal("0"),
        )
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.get(
            reverse("catalog:store_product_list"),
            {"brand": self.brand.pk, "stock": "in_stock"},
        )
        self.assertContains(response, "A Product")
        self.assertNotContains(response, "Zero Stock")

    def test_foreign_product_detail_404(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.get(
            reverse("catalog:store_product_detail", kwargs={"pk": self.product_b.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_foreign_product_edit_404(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:store_product_edit", kwargs={"pk": self.product_b.pk}),
            {"name": "Hacked", "sku": "HACK", "category": self.cat.pk, "store_price": "1"},
        )
        self.assertEqual(response.status_code, 404)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.name, "B Product")

    def test_foreign_product_images_404(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.get(
            reverse("catalog:store_product_images", kwargs={"pk": self.product_b.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_create_binds_to_request_store_ignores_store_id(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:store_product_create"),
            {
                "name": "Bound Product",
                "sku": "BOUND-1",
                "category": self.cat.pk,
                "brand": self.brand.pk,
                "store_price": "33.00",
                "unit": "KG",
                "unit_value": "1.5",
                "stock_quantity": "8",
                "low_stock_threshold": "2",
                "description": "",
                "store": self.store_b.pk,
                "store_id": self.store_b.pk,
                "is_featured": "on",
                "is_active": "on",
                "final_price": "1.00",
                "profit_margin": "99",
                "profit_margin_type": "FIXED",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(sku="BOUND-1")
        self.assertEqual(product.store_id, self.store_a.pk)
        self.assertEqual(product.status, ProductStatus.PENDING)
        self.assertFalse(product.is_featured)
        self.assertIsNone(product.final_price)
        self.assertFalse(product.profit_margin_type)
        self.assertEqual(product.unit_value, Decimal("1.500"))
        self.assertEqual(product.low_stock_threshold, Decimal("2.000"))

    def test_create_as_draft(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:store_product_create"),
            {
                "name": "Draft Product",
                "sku": "DRAFT-1",
                "category": self.cat.pk,
                "store_price": "12.00",
                "description": "",
                "save_as_draft": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(sku="DRAFT-1")
        self.assertEqual(product.status, ProductStatus.DRAFT)

    def test_submit_draft_post_only(self):
        draft = self.create_product(
            store=self.store_a,
            category=self.cat,
            sku="DRAFT-SUB",
            status=ProductStatus.DRAFT,
        )
        self.client.login(username="portal-a", password="secure-password-123")
        url = reverse("catalog:store_product_submit", kwargs={"pk": draft.pk})
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProductStatus.PENDING)

    def test_store_cannot_set_management_pricing_or_feature(self):
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:store_product_edit", kwargs={"pk": self.product_a.pk}),
            {
                "name": self.product_a.name,
                "sku": self.product_a.sku,
                "category": self.cat.pk,
                "brand": self.brand.pk,
                "store_price": "150.00",
                "unit": "PIECE",
                "unit_value": "1",
                "stock_quantity": "10",
                "low_stock_threshold": "3",
                "description": "",
                "final_price": "1.00",
                "selling_price": "1.00",
                "profit_margin": "999.00",
                "is_featured": "on",
                "is_active": "",
                "status": ProductStatus.APPROVED,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.store_price, Decimal("150.00"))
        self.assertIsNone(self.product_a.final_price)
        self.assertFalse(self.product_a.profit_margin_type)
        self.assertFalse(self.product_a.is_featured)
        self.assertTrue(self.product_a.is_active)
        self.assertNotEqual(self.product_a.status, ProductStatus.APPROVED)

    def test_edit_approved_commercial_fields_returns_pending(self):
        admin = User.objects.create_user(
            username="iso-admin",
            email="iso-admin@example.com",
            password="secure-password-123",
            role=Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        apply_admin_pricing(
            product=self.product_a,
            profit_margin_type=MarginType.FIXED,
            profit_margin=Decimal("10.00"),
            changed_by=admin,
        )
        self.attach_product_image(self.product_a)
        record_product_status_change(
            product=self.product_a,
            new_status=ProductStatus.APPROVED,
            changed_by=admin,
        )
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.status, ProductStatus.APPROVED)
        prior_selling = self.product_a.selling_price
        prior_final = self.product_a.final_price
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:store_product_edit", kwargs={"pk": self.product_a.pk}),
            {
                "name": self.product_a.name,
                "sku": self.product_a.sku,
                "category": self.cat.pk,
                "brand": self.brand.pk,
                "store_price": "199.00",
                "unit": "PIECE",
                "unit_value": "1",
                "stock_quantity": "10",
                "low_stock_threshold": "3",
                "description": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.status, ProductStatus.PENDING)
        self.assertEqual(self.product_a.store_price, Decimal("199.00"))
        self.assertEqual(self.product_a.selling_price, prior_selling)
        self.assertEqual(self.product_a.final_price, prior_final)
        self.assertFalse(product_is_publicly_available(self.product_a))
        self.assertTrue(
            ProductStatusHistory.objects.filter(
                product=self.product_a,
                old_status=ProductStatus.APPROVED,
                new_status=ProductStatus.PENDING,
            ).exists()
        )

    def test_suspended_store_blocked(self):
        self.store_a.status = StoreStatus.SUSPENDED
        self.store_a.save(update_fields=["status", "updated_at"])
        self.client.login(username="portal-a", password="secure-password-123")
        response = self.client.get(reverse("catalog:store_product_list"))
        self.assertEqual(response.status_code, 403)

    def test_images_url_shape(self):
        self.assertEqual(
            reverse("catalog:store_product_images", kwargs={"pk": self.product_a.pk}),
            f"/store/products/{self.product_a.pk}/images/",
        )


class TaxonomyPermissionTests(CatalogTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="tax-admin",
            email="tax-admin@example.com",
            password="secure-password-123",
            role=Role.ADMIN,
            is_staff=True,
        )

    def test_category_list_requires_permission(self):
        self.client.login(username="tax-admin", password="secure-password-123")
        self.assertEqual(
            self.client.get(reverse("catalog:category_list")).status_code, 403
        )
        self.grant_catalog_perms(self.admin, "view_productcategory")
        self.assertEqual(
            self.client.get(reverse("catalog:category_list")).status_code, 200
        )

    def test_create_brand(self):
        self.grant_catalog_perms(self.admin, "view_brand", "add_brand")
        self.client.login(username="tax-admin", password="secure-password-123")
        response = self.client.post(
            reverse("catalog:brand_create"),
            {"name": "NewBrand", "description": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Brand.objects.filter(name="NewBrand").exists())
