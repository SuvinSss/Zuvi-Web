"""One-row-per-request catalogue import: PENDING products priced later by management."""

import re
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from stores.models import Store, StoreStatus
from .decorators import user_has_catalog_permission
from .models import Product, ProductCategory, ProductStatus, ProductUnit
from .services import create_product

UNCATEGORISED = "Uncategorised"
SKU_PREFIX = "NP-"

_UNIT_ALIASES = {
    ProductUnit.KG: ("KG", "KGS", "KILO"),
    ProductUnit.GRAM: ("G", "GM", "GMS", "GR", "GRM", "GRAM", "GRAMS"),
    ProductUnit.LITER: ("L", "LT", "LTR", "LTRS", "LITRE", "LITRES", "LITER", "LITERS"),
    ProductUnit.ML: ("ML",),
}
_UNIT_BY_ALIAS = {alias: unit for unit, aliases in _UNIT_ALIASES.items() for alias in aliases}
_SIZE_RE = re.compile(
    r"(?<!\w)(\d+(?:\.\d+)?)\s*(%s)(?![A-Za-z])"
    % "|".join(sorted(_UNIT_BY_ALIAS, key=len, reverse=True)),
    re.IGNORECASE,
)


def parse_unit(name):
    """Return (unit, unit_value) from the last size in a name, e.g. '500GM' -> GRAM 500."""
    matches = _SIZE_RE.findall(name or "")
    if not matches:
        return ProductUnit.PIECE, Decimal("1")
    value, alias = matches[-1]
    value = Decimal(value)
    if value <= 0:
        return ProductUnit.PIECE, Decimal("1")
    return _UNIT_BY_ALIAS[alias.upper()], value


def clean_name(value, *, max_length):
    return " ".join(str(value or "").split())[:max_length]


def resolve_category(name, actor):
    name = clean_name(name, max_length=100) or UNCATEGORISED
    category = ProductCategory.objects.filter(name__iexact=name, is_active=True).first()
    if category is not None:
        return category, False
    if not user_has_catalog_permission(actor, "catalog.add_productcategory"):
        raise PermissionDenied(f"Category '{name}' does not exist and you cannot create categories.")
    category = ProductCategory(name=name)
    category.full_clean()
    category.save()
    return category, True


def import_row(*, store_id, sl_no, name, category_name, image, actor, request=None):
    """Create one PENDING product with Store Price 0. Safe to repeat."""
    if not user_has_catalog_permission(actor, "catalog.add_product"):
        raise PermissionDenied("Your account cannot add products.")
    try:
        sl_no = int(str(sl_no).strip())
    except ValueError:
        raise ValidationError("Sl.No must be a whole number.")
    if not 1 <= sl_no <= 99999:
        raise ValidationError("Sl.No must be between 1 and 99999.")
    name = clean_name(name, max_length=200)
    if not name:
        raise ValidationError("Product name is required.")
    if image is None:
        raise ValidationError("Product image is required.")
    sku = f"{SKU_PREFIX}{sl_no:04d}"
    if not str(store_id or "").isdecimal():
        raise ValidationError("Choose an active Store.")

    with transaction.atomic():
        store = Store.objects.select_for_update().filter(pk=int(store_id)).first()
        if store is None or not store.is_active or store.status != StoreStatus.ACTIVE:
            raise ValidationError("Choose an active Store.")
        existing = Product.objects.filter(store=store, sku=sku).first()
        if existing is not None:
            return {"state": "exists", "product_id": existing.pk, "sku": sku}
        duplicate = Product.objects.filter(store=store, name__iexact=name).first()
        if duplicate is not None:
            return {"state": "duplicate", "product_id": duplicate.pk, "sku": duplicate.sku}
        category, category_created = resolve_category(category_name, actor)
        unit, unit_value = parse_unit(name)
        product = create_product(
            store=store,
            product_data={
                "name": name,
                "sku": sku,
                "category": category,
                "unit": unit,
                "unit_value": unit_value,
                "store_price": Decimal("0.00"),
            },
            created_by=actor,
            images=[image],
            initial_status=ProductStatus.PENDING,
            request=request,
        )
    return {
        "state": "created",
        "product_id": product.pk,
        "sku": sku,
        "category": category.name,
        "category_created": category_created,
        "unit": f"{unit_value.normalize():f} {unit}",
    }
