from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.text import slugify

from .pricing import (
    DiscountType,
    MarginType,
    apply_calculated_prices,
)
from .validators import product_image_upload_to, validate_product_image


class ProductStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    INACTIVE = "INACTIVE", "Inactive"


class ProductUnit(models.TextChoices):
    PIECE = "PIECE", "Piece"
    PACK = "PACK", "Pack"
    BOX = "BOX", "Box"
    DOZEN = "DOZEN", "Dozen"
    KG = "KG", "Kilogram"
    GRAM = "GRAM", "Gram"
    LITER = "LITER", "Liter"
    ML = "ML", "Milliliter"
    METER = "METER", "Meter"


def _unique_slug(model_cls, base_slug, *, exclude_pk=None, field="slug"):
    candidate = base_slug
    suffix = 2
    while True:
        queryset = model_cls.objects.filter(**{field: candidate})
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


def _unique_slug_within_store(store_id, base_slug, *, exclude_pk=None):
    candidate = base_slug
    suffix = 2
    while True:
        queryset = Product.objects.filter(store_id=store_id, slug=candidate)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


class ProductCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "product categories"
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.pk and self.parent_id == self.pk:
                raise ValidationError({"parent": "A category cannot be its own parent."})
            ancestor = self.parent
            depth = 1
            seen = {self.pk} if self.pk else set()
            while ancestor is not None:
                if ancestor.pk in seen:
                    raise ValidationError(
                        {"parent": "Category parent hierarchy cannot contain a cycle."}
                    )
                seen.add(ancestor.pk)
                depth += 1
                if depth > 3:
                    raise ValidationError(
                        {
                            "parent": (
                                "Category hierarchy cannot exceed three levels."
                            )
                        }
                    )
                ancestor = ancestor.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "category"
            self.slug = _unique_slug(ProductCategory, base, exclude_pk=self.pk)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.parent_id:
            return f"{self.parent.name} / {self.name}"
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "brand"
            self.slug = _unique_slug(Brand, base, exclude_pk=self.pk)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "tag"
            self.slug = _unique_slug(Tag, base, exclude_pk=self.pk)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=64)
    product_code = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        blank=True,
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="products",
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    status = models.CharField(
        max_length=32,
        choices=ProductStatus.choices,
        default=ProductStatus.DRAFT,
    )
    is_active = models.BooleanField(default=True)
    unit = models.CharField(
        max_length=16,
        choices=ProductUnit.choices,
        default=ProductUnit.PIECE,
    )
    unit_value = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("1.000"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Numeric amount for the selected unit (e.g. 500 for 500 ml).",
    )
    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    low_stock_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Featured products are controlled by management only.",
    )
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    store_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    profit_margin_type = models.CharField(
        max_length=16,
        choices=MarginType.choices,
        blank=True,
    )
    profit_margin = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    discount_type = models.CharField(
        max_length=16,
        choices=DiscountType.choices,
        blank=True,
    )
    discount_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    final_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_products",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_products",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = (
            ("approve_product", "Can approve or reject products"),
            ("manage_product_pricing", "Can manage product pricing"),
        )
        constraints = [
            models.UniqueConstraint(
                fields=["store", "sku"],
                name="unique_sku_per_store",
            ),
            models.UniqueConstraint(
                fields=["store", "slug"],
                name="unique_slug_per_store",
            ),
            models.CheckConstraint(
                condition=models.Q(store_price__gte=Decimal("0")),
                name="product_store_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=Decimal("0")),
                name="product_stock_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_value__gte=Decimal("0")),
                name="product_unit_value_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(low_stock_threshold__gte=Decimal("0")),
                name="product_low_stock_threshold_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(selling_price__isnull=True)
                    | models.Q(selling_price__gte=Decimal("0"))
                ),
                name="product_selling_price_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(final_price__isnull=True)
                    | models.Q(final_price__gte=Decimal("0"))
                ),
                name="product_final_price_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(profit_margin__isnull=True)
                    | models.Q(profit_margin__gte=Decimal("0"))
                ),
                name="product_profit_margin_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(discount_value__isnull=True)
                    | models.Q(discount_value__gte=Decimal("0"))
                ),
                name="product_discount_value_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manufacturing_date__isnull=True)
                    | models.Q(expiry_date__isnull=True)
                    | models.Q(expiry_date__gte=models.F("manufacturing_date"))
                ),
                name="product_expiry_on_or_after_manufacturing",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.store_price is not None and self.store_price < 0:
            errors["store_price"] = "Store price cannot be negative."

        if self.stock_quantity is not None and self.stock_quantity < 0:
            errors["stock_quantity"] = "Stock quantity cannot be negative."

        if self.unit_value is not None and self.unit_value < 0:
            errors["unit_value"] = "Unit value cannot be negative."

        if self.low_stock_threshold is not None and self.low_stock_threshold < 0:
            errors["low_stock_threshold"] = "Low-stock threshold cannot be negative."

        if self.profit_margin is not None and self.profit_margin < 0:
            errors["profit_margin"] = "Profit margin cannot be negative."

        if self.discount_value is not None and self.discount_value < 0:
            errors["discount_value"] = "Discount value cannot be negative."

        if (
            self.profit_margin_type == MarginType.PERCENTAGE
            and self.profit_margin is not None
            and self.profit_margin > Decimal("100")
        ):
            errors["profit_margin"] = "Percentage margin cannot exceed 100."

        if (
            self.discount_type == DiscountType.PERCENTAGE
            and self.discount_value is not None
            and self.discount_value > Decimal("100")
        ):
            errors["discount_value"] = "Percentage discount cannot exceed 100."

        today = timezone.localdate()
        if self.manufacturing_date and self.manufacturing_date > today:
            errors["manufacturing_date"] = "Manufacturing date cannot be in the future."

        if (
            self.manufacturing_date
            and self.expiry_date
            and self.expiry_date < self.manufacturing_date
        ):
            errors["expiry_date"] = (
                "Expiry date must be on or after the manufacturing date."
            )

        if errors:
            raise ValidationError(errors)

        # Never trust selling_price / final_price from forms or callers.
        apply_calculated_prices(self)

    def save(self, *args, **kwargs):
        if self.store_id and not self.slug:
            base = slugify(self.name) or "product"
            self.slug = _unique_slug_within_store(
                self.store_id, base, exclude_pk=self.pk
            )

        if self.product_code:
            return super().save(*args, **kwargs)

        from .services import PRODUCT_CODE_MAX_ATTEMPTS, generate_product_code

        last_error = None
        for _ in range(PRODUCT_CODE_MAX_ATTEMPTS):
            self.product_code = generate_product_code(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.product_code = ""
                if self.pk:
                    raise
        raise IntegrityError(
            "Could not allocate a unique product code under concurrent load."
        ) from last_error

    def __str__(self):
        return f"{self.name} ({self.product_code or 'new'})"


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(
        upload_to=product_image_upload_to,
        validators=[validate_product_image],
    )
    alt_text = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=models.Q(is_primary=True),
                name="unique_primary_product_image_per_product",
            ),
        ]

    def __str__(self):
        primary = "primary" if self.is_primary else "image"
        code = self.product.product_code if self.product_id else "new"
        return f"{code} {primary}"


class ProductStatusHistory(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=32,
        choices=ProductStatus.choices,
        blank=True,
    )
    new_status = models.CharField(max_length=32, choices=ProductStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="product_status_changes",
    )
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "product status histories"
        ordering = ["-created_at"]

    def __str__(self):
        old = self.old_status or "—"
        code = self.product.product_code if self.product_id else "new"
        return f"{code}: {old} → {self.new_status}"


class ProductPriceHistory(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="price_history",
    )
    store_price = models.DecimalField(max_digits=12, decimal_places=2)
    profit_margin_type = models.CharField(
        max_length=16,
        choices=MarginType.choices,
        blank=True,
    )
    profit_margin = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    discount_type = models.CharField(
        max_length=16,
        choices=DiscountType.choices,
        blank=True,
    )
    discount_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    final_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="product_price_changes",
    )
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "product price histories"
        ordering = ["-created_at"]

    def __str__(self):
        code = self.product.product_code if self.product_id else "new"
        return f"{code} price @ {self.created_at}"
