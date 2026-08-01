from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .models import Brand, ProductCategory


def _bootstrap(form):
    for _name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-check-input".strip()
        elif isinstance(widget, forms.Select):
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-select".strip()
        else:
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-control".strip()


class PublicProductFilterForm(forms.Form):
    SORT_CHOICES = (
        ("newest", "Newest"),
        ("name", "Name A–Z"),
        ("name_desc", "Name Z–A"),
        ("price", "Price: low to high"),
        ("price_desc", "Price: high to low"),
    )

    q = forms.CharField(required=False, label="Search")
    category = forms.SlugField(required=False)
    brand = forms.SlugField(required=False)
    min_price = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        label="Min price",
    )
    max_price = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        label="Max price",
    )
    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False, initial="newest")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"] = forms.ChoiceField(
            required=False,
            choices=[("", "All categories")]
            + list(
                ProductCategory.objects.filter(is_active=True)
                .order_by("name")
                .values_list("slug", "name")
            ),
        )
        self.fields["brand"] = forms.ChoiceField(
            required=False,
            choices=[("", "All brands")]
            + list(
                Brand.objects.filter(is_active=True)
                .order_by("name")
                .values_list("slug", "name")
            ),
        )
        self.fields["sort"].choices = self.SORT_CHOICES
        _bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        min_price = cleaned.get("min_price")
        max_price = cleaned.get("max_price")
        if (
            min_price is not None
            and max_price is not None
            and min_price > max_price
        ):
            raise ValidationError(
                {"max_price": "Max price must be greater than or equal to min price."}
            )
        return cleaned


class PublicAddToCartForm(forms.Form):
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
        initial=Decimal("1.000"),
        label="Quantity",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
