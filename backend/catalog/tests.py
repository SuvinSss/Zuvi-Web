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

    def test_stock_quantity_ignored_on_catalogue_update(self):
        """Catalogue updates must not change stock; inventory service owns balances."""
        before = self.product.stock_quantity
        self._store_edit(stock_quantity=Decimal("25.000"))
        self._assert_stays_approved()
        self.assertEqual(self.product.stock_quantity, before)

    def test_low_stock_threshold_alone_stays_approved(self):
        self._store_edit(low_stock_threshold=Decimal("5.000"))
        self._assert_stays_approved()
        self.assertEqual(self.product.low_stock_threshold, Decimal("5.000"))

    def test_threshold_update_does_not_change_stock(self):
        before = self.product.stock_quantity
        self._store_edit(
            stock_quantity=Decimal("8.000"),
            low_stock_threshold=Decimal("4.000"),
        )
        self._assert_stays_approved()
        self.assertEqual(self.product.stock_quantity, before)
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
        before = self.product.stock_quantity
        self._store_edit(
            name=self.product.name,
            store_price=self.product.store_price,
            stock_quantity=Decimal("11.000"),
        )
        self._assert_stays_approved()
        self.assertEqual(self.product.stock_quantity, before)

    def test_mixed_ignored_stock_and_name_change_returns_pending(self):
        before = self.product.stock_quantity
        self._store_edit(
            name="Mixed Edit",
            stock_quantity=Decimal("50.000"),
        )
        self._assert_returned_to_pending(expected_fields=["name"])
        self.assertEqual(self.product.stock_quantity, before)

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



















    def test_django_admin_status_and_prices_readonly(self):
        from catalog.admin import ProductAdmin

        self.assertIn("status", ProductAdmin.readonly_fields)
        self.assertIn("selling_price", ProductAdmin.readonly_fields)
        self.assertIn("final_price", ProductAdmin.readonly_fields)
        self.assertIn("product_code", ProductAdmin.readonly_fields)
        self.assertIn("stock_quantity", ProductAdmin.readonly_fields)


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
















