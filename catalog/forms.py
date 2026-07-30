from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal

from stores.models import Store

from .models import Brand, Product, ProductCategory, ProductStatus, ProductUnit, Tag
from .pricing import DiscountType, MarginType
from .status import allowed_next_statuses, reason_required_for


def _apply_bootstrap(form):
    for _name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, forms.SelectMultiple):
            widget.attrs.setdefault("class", "form-select")
            widget.attrs.setdefault("size", "6")
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        elif isinstance(widget, forms.FileInput):
            widget.attrs.setdefault("class", "form-control")
        elif isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", "form-control")
            widget.attrs.setdefault("rows", 3)
        else:
            widget.attrs.setdefault("class", "form-control")


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ("name", "parent", "description", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ProductCategory.objects.filter(is_active=True).order_by("name")
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
            # Exclude descendants to reduce accidental cycles.
            descendant_ids = set()
            stack = list(self.instance.children.all())
            while stack:
                child = stack.pop()
                descendant_ids.add(child.pk)
                stack.extend(list(child.children.all()))
            if descendant_ids:
                qs = qs.exclude(pk__in=descendant_ids)
        self.fields["parent"].queryset = qs
        self.fields["parent"].required = False
        _apply_bootstrap(self)


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ("name", "description", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ("name", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)


class ManagementProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "store",
            "name",
            "slug",
            "description",
            "sku",
            "category",
            "brand",
            "tags",
            "unit",
            "unit_value",
            "low_stock_threshold",
            "manufacturing_date",
            "expiry_date",
            "store_price",
            "is_active",
            "is_featured",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Leave blank to auto-generate from the name."
        self.fields["unit"].required = False
        self.fields["unit_value"].required = False
        self.fields["low_stock_threshold"].required = False
        self.fields["manufacturing_date"].required = False
        self.fields["expiry_date"].required = False
        self.fields["category"].queryset = ProductCategory.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["brand"].required = False
        self.fields["tags"].queryset = Tag.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["tags"].required = False
        self.fields["store"].queryset = Store.objects.order_by("name")
        if self.instance and self.instance.pk:
            # Store is immutable after create.
            self.fields["store"].disabled = True
            if self.instance.category_id:
                self.fields["category"].queryset = (
                    ProductCategory.objects.filter(is_active=True)
                    | ProductCategory.objects.filter(pk=self.instance.category_id)
                ).distinct().order_by("name")
            if self.instance.brand_id:
                self.fields["brand"].queryset = (
                    Brand.objects.filter(is_active=True)
                    | Brand.objects.filter(pk=self.instance.brand_id)
                ).distinct().order_by("name")
        _apply_bootstrap(self)

    def clean_unit(self):
        return self.cleaned_data.get("unit") or ProductUnit.PIECE

    def clean_unit_value(self):
        value = self.cleaned_data.get("unit_value")
        return value if value is not None else Decimal("1.000")

    def clean_low_stock_threshold(self):
        value = self.cleaned_data.get("low_stock_threshold")
        return value if value is not None else Decimal("0.000")

    def clean_slug(self):
        return (self.cleaned_data.get("slug") or "").strip()


class ManagementProductCreateForm(ManagementProductForm):
    save_as_draft = forms.BooleanField(
        required=False,
        label="Save as draft",
        help_text="Otherwise the product is created as PENDING.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)


class StoreProductForm(forms.ModelForm):
    """
    Store portal form — catalogue fields and store_price only.

    stock_quantity is intentionally omitted; stock changes must go through
    the inventory service so every movement creates an InventoryTransaction.
    """

    class Meta:
        model = Product
        fields = (
            "name",
            "sku",
            "category",
            "brand",
            "tags",
            "description",
            "unit",
            "unit_value",
            "store_price",
            "low_stock_threshold",
            "manufacturing_date",
            "expiry_date",
        )
        labels = {
            "unit_value": "Unit value",
            "low_stock_threshold": "Low-stock threshold",
            "store_price": "Store price",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].required = False
        self.fields["unit_value"].required = False
        self.fields["low_stock_threshold"].required = False
        self.fields["manufacturing_date"].required = False
        self.fields["expiry_date"].required = False
        self.fields["category"].queryset = ProductCategory.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["brand"].required = False
        self.fields["tags"].queryset = Tag.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["tags"].required = False
        if self.instance and self.instance.pk:
            if self.instance.category_id:
                self.fields["category"].queryset = (
                    ProductCategory.objects.filter(is_active=True)
                    | ProductCategory.objects.filter(pk=self.instance.category_id)
                ).distinct().order_by("name")
            if self.instance.brand_id:
                self.fields["brand"].queryset = (
                    Brand.objects.filter(is_active=True)
                    | Brand.objects.filter(pk=self.instance.brand_id)
                ).distinct().order_by("name")
        _apply_bootstrap(self)

    def clean_unit(self):
        return self.cleaned_data.get("unit") or ProductUnit.PIECE

    def clean_unit_value(self):
        value = self.cleaned_data.get("unit_value")
        return value if value is not None else Decimal("1.000")

    def clean_low_stock_threshold(self):
        value = self.cleaned_data.get("low_stock_threshold")
        return value if value is not None else Decimal("0.000")


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class StoreProductCreateForm(StoreProductForm):
    save_as_draft = forms.BooleanField(
        required=False,
        label="Save as draft",
        help_text="Leave unchecked to submit for approval (PENDING).",
    )
    images = forms.FileField(
        required=False,
        widget=MultipleFileInput(attrs={"class": "form-control", "multiple": True}),
        label="Product images",
        help_text="Optional. You can select multiple images.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)

    def clean_images(self):
        from .validators import MAX_IMAGES_PER_PRODUCT, validate_product_image

        files = self.files.getlist("images") if self.files else []
        cleaned = []
        for uploaded in files:
            if not uploaded:
                continue
            try:
                validate_product_image(uploaded)
            except ValidationError as exc:
                raise forms.ValidationError(exc.messages)
            cleaned.append(uploaded)
        if len(cleaned) > MAX_IMAGES_PER_PRODUCT:
            raise forms.ValidationError(
                f"A product may have at most {MAX_IMAGES_PER_PRODUCT} images."
            )
        return cleaned


class ProductPricingForm(forms.Form):
    """
    Management pricing inputs only.

    Selling and final prices are never accepted from the browser — they are
    recalculated on the backend from store_price + margin/discount.
    """

    profit_margin_type = forms.ChoiceField(
        choices=MarginType.choices,
        label="Profit margin type",
    )
    profit_margin = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        label="Profit margin",
    )
    discount_type = forms.ChoiceField(
        choices=[("", "No discount"), *DiscountType.choices],
        required=False,
        label="Discount type",
    )
    discount_value = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=Decimal("0.00"),
        label="Discount value",
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Change reason",
    )

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        if product is not None and not args:
            self.fields["profit_margin_type"].initial = product.profit_margin_type
            self.fields["profit_margin"].initial = product.profit_margin
            self.fields["discount_type"].initial = product.discount_type or ""
            self.fields["discount_value"].initial = product.discount_value
        _apply_bootstrap(self)

    def clean_profit_margin(self):
        value = self.cleaned_data["profit_margin"]
        if value is not None and value < 0:
            raise forms.ValidationError("Profit margin cannot be negative.")
        return value

    def clean_discount_value(self):
        value = self.cleaned_data.get("discount_value")
        if value is not None and value < 0:
            raise forms.ValidationError("Discount value cannot be negative.")
        return value

    def clean(self):
        from .pricing import calculate_prices

        cleaned = super().clean()
        discount_type = cleaned.get("discount_type") or ""
        discount_value = cleaned.get("discount_value")
        if not discount_type:
            cleaned["discount_type"] = ""
            cleaned["discount_value"] = (
                discount_value if discount_value is not None else Decimal("0.00")
            )
        elif discount_value is None:
            cleaned["discount_value"] = Decimal("0.00")

        margin_type = cleaned.get("profit_margin_type")
        margin = cleaned.get("profit_margin")
        if self.product is None or margin_type is None or margin is None:
            return cleaned

        if (
            margin_type == MarginType.PERCENTAGE
            and margin is not None
            and margin > Decimal("100")
        ):
            self.add_error(
                "profit_margin", "Percentage margin cannot exceed 100."
            )
            return cleaned

        if (
            discount_type == DiscountType.PERCENTAGE
            and cleaned.get("discount_value") is not None
            and cleaned["discount_value"] > Decimal("100")
        ):
            self.add_error(
                "discount_value", "Percentage discount must be between 0 and 100."
            )
            return cleaned

        try:
            selling, final = calculate_prices(
                store_price=self.product.store_price,
                profit_margin_type=margin_type,
                profit_margin=margin,
                discount_type=cleaned["discount_type"],
                discount_value=cleaned["discount_value"],
            )
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                for field, errors in exc.message_dict.items():
                    target = field if field in self.fields else None
                    for error in errors:
                        self.add_error(target, error)
            else:
                self.add_error(None, exc)
            return cleaned

        cleaned["selling_price_preview"] = selling
        cleaned["final_price_preview"] = final
        return cleaned


class ProductStatusChangeForm(forms.Form):
    new_status = forms.ChoiceField(choices=[])
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, current_status=None, allowed_statuses=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_status = current_status
        statuses = allowed_statuses
        if statuses is None and current_status is not None:
            statuses = allowed_next_statuses(current_status)
        choices = [
            (value, label)
            for value, label in ProductStatus.choices
            if value in (statuses or [])
        ]
        self.fields["new_status"].choices = choices
        _apply_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        new_status = cleaned.get("new_status")
        reason = cleaned.get("reason", "")
        if new_status and reason_required_for(new_status) and not (reason or "").strip():
            self.add_error("reason", "A reason is required when rejecting a product.")
        return cleaned


class ProductImageForm(forms.Form):
    image = forms.ImageField(
        help_text="JPEG, PNG or WebP · max 5 MB. Up to 5 images per product.",
    )
    alt_text = forms.CharField(required=False, max_length=200)
    sort_order = forms.IntegerField(required=False, min_value=0, initial=0)
    is_primary = forms.BooleanField(
        required=False,
        label="Set as primary image",
        help_text=(
            "The first image is primary automatically. "
            "Checking this replaces the current primary."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self)

    def clean_image(self):
        image = self.cleaned_data["image"]
        from .validators import validate_product_image

        try:
            validate_product_image(image)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return image
