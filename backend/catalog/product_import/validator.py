"""Authoritative row validation for bulk import (the browser is never trusted).

``analyse`` is used for the preview and again, against fresh database state,
at commit time. Lookups are batched so 1000 rows cost a handful of queries.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils import timezone

from catalog.models import Brand, Product, ProductCategory, ProductImportBatch, ProductUnit, Tag
from catalog.pricing import quantize_money
from stores.models import Store

from .images import ZipImages, validate_image_url


@dataclass
class RowResult:
    number: int
    sku: str = ""
    name: str = ""
    store_code: str = ""
    action: str = ""  # create | update | skip | "" when invalid
    errors: list = field(default_factory=list)  # [(column, message)]
    duplicate: bool = False
    image: str = "none"  # none | zip | url
    data: dict = field(default_factory=dict)  # cleaned product fields (valid rows)
    store_id: int | None = None
    existing_id: int | None = None
    tag_ids: list = field(default_factory=list)
    image_ref: str = ""
    image_alt: str = ""

    @property
    def valid(self):
        return not self.errors

    def public(self):
        status = "invalid" if self.errors else ("skip" if self.action == "skip" else "valid")
        return {
            "row": self.number, "status": status, "action": self.action or None,
            "store_code": self.store_code, "sku": self.sku, "name": self.name,
            "duplicate": self.duplicate, "image": self.image,
            "errors": [{"column": c, "message": m} for c, m in self.errors],
        }


@dataclass
class Analysis:
    rows: list
    ignored_columns: list = field(default_factory=list)

    @property
    def counts(self):
        return {
            "total": len(self.rows),
            "valid": sum(1 for r in self.rows if r.valid),
            "invalid": sum(1 for r in self.rows if not r.valid),
            "duplicates": sum(1 for r in self.rows if r.duplicate),
            "create": sum(1 for r in self.rows if r.valid and r.action == "create"),
            "update": sum(1 for r in self.rows if r.valid and r.action == "update"),
            "skip": sum(1 for r in self.rows if r.valid and r.action == "skip"),
        }

    def error_list(self, cap=1000):
        out = []
        for r in self.rows:
            for column, message in r.errors:
                out.append({"row": r.number, "column": column, "message": message, "sku": r.sku})
        return out[:cap]


def _text(value):
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(int(value)) if value == value.to_integral_value() else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip()


def _decimal(value, column, errors, *, places, required=False, default=None, max_digits=12):
    if value is None or value == "":
        if required:
            errors.append((column, "This field is required."))
        return default
    try:
        number = Decimal(str(value).replace(",", "")) if not isinstance(value, Decimal) else value
    except InvalidOperation:
        errors.append((column, "Enter a valid number."))
        return default
    if not number.is_finite():
        errors.append((column, "Enter a valid number."))
        return default
    if number < 0:
        errors.append((column, "Must not be negative."))
        return default
    if number != number.quantize(Decimal(1).scaleb(-places)):
        errors.append((column, f"Use at most {places} decimal places."))
        return default
    quantised = number.quantize(Decimal(1).scaleb(-places))
    if len(quantised.as_tuple().digits) > max_digits:
        errors.append((column, "Number is too large."))
        return default
    return quantised


def _date(value, column, errors):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        errors.append((column, "Use the format YYYY-MM-DD."))
        return None


class Lookups:
    """Batched reference data for one file."""

    def __init__(self, raw_rows):
        codes = {_text(r.values.get("store_code")).lower() for r in raw_rows} - {""}
        self.stores = {
            s.store_code.lower(): s
            for s in Store.objects.annotate(code_lower=Lower("store_code")).filter(code_lower__in=codes)
        }
        self.categories = {}
        for category in ProductCategory.objects.filter(is_active=True).select_related("parent__parent"):
            for key in {category.name.lower(), str(category).lower()}:
                self.categories.setdefault(key, []).append(category)
        self.brands = {b.name.lower(): b for b in Brand.objects.filter(is_active=True)}
        self.tags = {t.name.lower(): t for t in Tag.objects.filter(is_active=True)}
        store_ids = {s.pk for s in self.stores.values()}
        skus = {_text(r.values.get("sku")) for r in raw_rows}
        self.existing = {
            (p.store_id, p.sku): p for p in Product.objects.filter(store_id__in=store_ids, sku__in=skus)
        }
        self.units = {u.lower(): u for u in ProductUnit.values} | {
            label.lower(): value for value, label in ProductUnit.choices
        }


def analyse(raw_rows, ignored_columns, *, mode, allow_image_urls, zip_images: ZipImages, check_urls=True) -> Analysis:
    lookups = Lookups(raw_rows)
    seen = {}
    results = []
    for raw in raw_rows:
        result = RowResult(raw.number, errors=list(raw.errors))
        _validate_row(raw, result, lookups, mode, allow_image_urls, zip_images, seen, check_urls)
        results.append(result)
    return Analysis(results, ignored_columns)


def _validate_row(raw, result, lookups, mode, allow_image_urls, zip_images, seen, check_urls):
    v, errors = raw.values, result.errors
    result.store_code = _text(v.get("store_code"))
    result.sku = _text(v.get("sku"))
    result.name = _text(v.get("name"))
    data = {}

    for column, length in (("sku", 64), ("name", 200)):
        value = _text(v.get(column))
        if not value:
            errors.append((column, "This field is required."))
        elif len(value) > length:
            errors.append((column, f"Must be {length} characters or fewer."))
    data["sku"], data["name"] = result.sku, result.name
    data["description"] = _text(v.get("description"))

    store = lookups.stores.get(result.store_code.lower()) if result.store_code else None
    if not result.store_code:
        errors.append(("store_code", "This field is required."))
    elif store is None:
        errors.append(("store_code", f"Store '{result.store_code}' was not found."))
    else:
        result.store_id = store.pk

    category_name = _text(v.get("category"))
    if not category_name:
        errors.append(("category", "This field is required."))
    else:
        matches = lookups.categories.get(category_name.lower(), [])
        if not matches:
            errors.append(("category", f"Category '{category_name}' was not found."))
        elif len(matches) > 1:
            errors.append(("category", f"Category '{category_name}' is ambiguous; use 'Parent / Child'."))
        else:
            data["category"] = matches[0]

    brand_name = _text(v.get("brand"))
    if brand_name:
        brand = lookups.brands.get(brand_name.lower())
        if brand is None:
            errors.append(("brand", f"Brand '{brand_name}' was not found."))
        else:
            data["brand"] = brand

    tag_names = [t.strip() for t in _text(v.get("tags")).split(",") if t.strip()]
    for name in tag_names:
        tag = lookups.tags.get(name.lower())
        if tag is None:
            errors.append(("tags", f"Tag '{name}' was not found."))
        elif tag.pk not in result.tag_ids:
            result.tag_ids.append(tag.pk)

    data["store_price"] = _decimal(v.get("store_price"), "store_price", errors, places=2, required=True)
    data["unit_value"] = _decimal(v.get("unit_value"), "unit_value", errors, places=3, default=Decimal("1.000"))
    data["low_stock_threshold"] = _decimal(
        v.get("low_stock_threshold"), "low_stock_threshold", errors, places=3, default=Decimal("0.000")
    )
    unit = _text(v.get("unit"))
    if unit:
        resolved = lookups.units.get(unit.lower())
        if resolved is None:
            errors.append(("unit", f"Unknown unit '{unit}'."))
        else:
            data["unit"] = resolved
    manufacturing = _date(v.get("manufacturing_date"), "manufacturing_date", errors)
    expiry = _date(v.get("expiry_date"), "expiry_date", errors)
    if manufacturing and manufacturing > timezone.localdate():
        errors.append(("manufacturing_date", "Manufacturing date cannot be in the future."))
    if manufacturing and expiry and expiry < manufacturing:
        errors.append(("expiry_date", "Expiry date must be on or after the manufacturing date."))
    data["manufacturing_date"], data["expiry_date"] = manufacturing, expiry

    # Duplicates: inside the file, then against existing products.
    if result.store_id and result.sku:
        key = (result.store_id, result.sku.lower())
        if key in seen:
            result.duplicate = True
            errors.append(("sku", f"Duplicate of row {seen[key]} in this file."))
        else:
            seen[key] = raw.number
            existing = lookups.existing.get((result.store_id, result.sku))
            if existing is not None:
                result.duplicate = True
                result.existing_id = existing.pk
                if mode == ProductImportBatch.Mode.CREATE:
                    errors.append(("sku", "A product with this SKU already exists in the store."))
                elif mode == ProductImportBatch.Mode.SKIP:
                    result.action = "skip"
                else:
                    result.action = "update"
            else:
                result.action = "create"

    _validate_image(v, result, allow_image_urls, zip_images, check_urls)
    result.data = data
    if errors:
        result.action = ""


def _validate_image(v, result, allow_image_urls, zip_images, check_urls):
    errors = result.errors
    file_name, url = _text(v.get("image_file")), _text(v.get("image_url"))
    alt = _text(v.get("image_alt_text"))
    if len(alt) > 200:
        errors.append(("image_alt_text", "Must be 200 characters or fewer."))
    result.image_alt = alt
    if file_name and url:
        errors.append(("image_url", "Use either image_file or image_url, not both."))
        return
    if file_name:
        if file_name not in zip_images:
            errors.append(("image_file", f"'{file_name}' was not found in the uploaded images ZIP."))
        else:
            result.image, result.image_ref = "zip", file_name
    elif url:
        if not allow_image_urls:
            errors.append(("image_url", "Image URLs are disabled for this import. Tick 'Allow image URLs' or remove the value."))
            return
        try:
            if check_urls:
                validate_image_url(url)
        except ValidationError as exc:
            errors.append(("image_url", exc.messages[0]))
        else:
            result.image, result.image_ref = "url", url
