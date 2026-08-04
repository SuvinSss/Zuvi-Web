import secrets
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalog.models import Product
from stores.models import Store

PURCHASE_SUBMISSION_SESSION_KEY = "inventory_purchase_submission_token"


def issue_purchase_submission_token(request):
    """Issue a one-time token to reduce accidental double-submit of purchases."""
    token = secrets.token_urlsafe(24)
    request.session[PURCHASE_SUBMISSION_SESSION_KEY] = token
    return token


def consume_purchase_submission_token(request, submitted_token):
    """
    Consume the session purchase token.

    Returns True only when the submitted token matches the current session token.
    A successful consume clears the session key so a replay cannot re-create stock.
    """
    expected = request.session.pop(PURCHASE_SUBMISSION_SESSION_KEY, None)
    if not expected or not submitted_token:
        return False
    return secrets.compare_digest(str(expected), str(submitted_token))


def _date_input(**extra_attrs):
    """HTML5 date picker widget (ISO value format for browser compatibility)."""
    attrs = {"type": "date", **extra_attrs}
    return forms.DateInput(attrs=attrs, format="%Y-%m-%d")


def _apply_bootstrap(form):
    for _name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        elif isinstance(widget, forms.Textarea):
            widget.attrs.setdefault("class", "form-control")
            widget.attrs.setdefault("rows", 2)
        else:
            widget.attrs.setdefault("class", "form-control")


class InventoryMovementForm(forms.Form):
    """Single-product stock movement. Store is never chosen by Store Users."""

    product = forms.ModelChoiceField(queryset=Product.objects.none())
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
    )
    reason = forms.CharField(required=False, widget=forms.Textarea)
    notes = forms.CharField(required=False, widget=forms.Textarea)
    reference = forms.CharField(required=False, max_length=100)
    unit_cost = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
    )
    manufacturing_date = forms.DateField(
        required=False,
        widget=_date_input(),
        input_formats=["%Y-%m-%d"],
    )
    expiry_date = forms.DateField(
        required=False,
        widget=_date_input(),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(
        self,
        *args,
        product_queryset=None,
        store=None,
        require_reason=False,
        locked_store=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.store = store
        self.locked_store = locked_store
        self.require_reason = require_reason
        qs = product_queryset if product_queryset is not None else Product.objects.none()
        if locked_store is not None:
            qs = qs.filter(store_id=locked_store.pk)
        self.fields["product"].queryset = qs.order_by("name")
        if require_reason:
            self.fields["reason"].required = True
        _apply_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        expected_store = self.locked_store or self.store
        if product and expected_store and product.store_id != expected_store.pk:
            raise ValidationError(
                {"product": "Product must belong to the selected store."}
            )
        if self.require_reason and not (cleaned.get("reason") or "").strip():
            self.add_error("reason", "A reason is required for this stock movement.")
        return cleaned


class ManagementInventoryMovementForm(InventoryMovementForm):
    """Management form may optionally scope by store."""

    store = forms.ModelChoiceField(queryset=Store.objects.all(), required=False)

    def __init__(self, *args, store_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if store_queryset is not None:
            self.fields["store"].queryset = store_queryset.order_by("name")
        _apply_bootstrap(self)

    def clean(self):
        cleaned = super(InventoryMovementForm, self).clean()
        store = cleaned.get("store")
        product = cleaned.get("product")
        if product and not store:
            store = product.store
            cleaned["store"] = store
        expected_store = self.locked_store or store or self.store
        if product and expected_store and product.store_id != expected_store.pk:
            self.add_error("product", "Product must belong to the selected store.")
        if self.require_reason and not (cleaned.get("reason") or "").strip():
            self.add_error("reason", "A reason is required for this stock movement.")
        cleaned["store"] = expected_store or (product.store if product else None)
        return cleaned


class ProductScopedMovementForm(forms.Form):
    """
    Movement form for a fixed product (management product inventory pages).

    Store is taken from the product — never chosen in the form.
    """

    quantity = forms.DecimalField(
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
    )
    reason = forms.CharField(required=False, widget=forms.Textarea)
    notes = forms.CharField(required=False, widget=forms.Textarea)
    reference = forms.CharField(required=False, max_length=100)
    unit_cost = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
    )
    manufacturing_date = forms.DateField(
        required=False,
        widget=_date_input(),
        input_formats=["%Y-%m-%d"],
    )
    expiry_date = forms.DateField(
        required=False,
        widget=_date_input(),
        input_formats=["%Y-%m-%d"],
    )
    direction = forms.ChoiceField(
        choices=(("IN", "Adjustment in"), ("OUT", "Adjustment out")),
        required=False,
    )

    def __init__(self, *args, product=None, require_reason=False, show_direction=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        self.require_reason = require_reason
        if not show_direction:
            self.fields.pop("direction", None)
        if require_reason:
            self.fields["reason"].required = True
        _apply_bootstrap(self)

    def clean(self):
        cleaned = super().clean()
        if self.require_reason and not (cleaned.get("reason") or "").strip():
            self.add_error("reason", "A reason is required for this stock movement.")
        return cleaned


class PurchaseEntryCreateForm(forms.Form):
    """
    Single-line purchase create form.

    Store is never a form field: management derives it from the product;
    store portal locks it to the authenticated StoreUser membership.
    """

    submission_token = forms.CharField(widget=forms.HiddenInput)
    supplier_name = forms.CharField(max_length=200)
    supplier_invoice_number = forms.CharField(required=False, max_length=100)
    entry_date = forms.DateField(
        initial=timezone.localdate,
        widget=_date_input(),
        input_formats=["%Y-%m-%d"],
    )
    notes = forms.CharField(required=False, widget=forms.Textarea)
    product = forms.ModelChoiceField(queryset=Product.objects.none())
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"),
        max_digits=12,
        decimal_places=3,
    )
    unit_cost = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        help_text="Purchase unit cost preserved for profit and cost reports.",
    )

    def __init__(
        self,
        *args,
        product_queryset=None,
        locked_store=None,
        submission_token=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.locked_store = locked_store
        qs = product_queryset if product_queryset is not None else Product.objects.none()
        if locked_store is not None:
            qs = qs.filter(store_id=locked_store.pk)
        self.fields["product"].queryset = qs.order_by("name")
        if submission_token is not None and not self.is_bound:
            self.fields["submission_token"].initial = submission_token
        _apply_bootstrap(self)

    def clean_product(self):
        product = self.cleaned_data["product"]
        if self.locked_store and product.store_id != self.locked_store.pk:
            raise ValidationError("Product must belong to your store.")
        return product

    def clean_entry_date(self):
        entry_date = self.cleaned_data["entry_date"]
        if entry_date > timezone.localdate():
            raise ValidationError("Purchase entry date cannot be in the future.")
        return entry_date
