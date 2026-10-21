"""Authoritative row validation for bulk import (the browser is never trusted).

``analyse`` is used for the preview and again, against fresh database state,
at commit time. Lookups are batched so 1000 rows cost a handful of queries.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify

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
    generated: dict = field(default_factory=dict)   # values the system filled in (marked in the UI and on the product)
    normalized: dict = field(default_factory=dict)  # {column: [before, after]} deterministic clean-ups
    values: dict = field(default_factory=dict)      # what the user sees / can correct, after overrides

    @property
    def valid(self):
        return not self.errors

    @property
    def recoverable(self):
        """Only missing or unresolved values: the user can supply them and retry."""
        return bool(self.errors) and all(
            m == "This field is required." or "was not found" in m or "is ambiguous" in m for _c, m in self.errors
        )

    @property
    def kind(self):
        if not self.errors:
            return "skip" if self.action == "skip" else "valid"
        return "incomplete" if self.recoverable else "invalid"

    def public(self):
        return {
            "row": self.number, "status": self.kind, "action": self.action or None,
            "store_code": self.store_code, "sku": self.sku, "name": self.name,
            "duplicate": self.duplicate, "image": self.image, "values": self.values,
            "generated": sorted(self.generated), "normalized": self.normalized,
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
            "incomplete": sum(1 for r in self.rows if r.kind == "incomplete"),
            "hard_invalid": sum(1 for r in self.rows if r.kind == "invalid"),
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


UNIT_SYNONYMS = {
    "pc": "PIECE", "pcs": "PIECE", "piece": "PIECE", "pieces": "PIECE", "nos": "PIECE", "kgs": "KG", "kilogram": "KG",
    "g": "GRAM", "gm": "GRAM", "gms": "GRAM", "grams": "GRAM", "l": "LITER", "ltr": "LITER", "litre": "LITER",
    "liter": "LITER", "ml": "ML", "m": "METER", "mtr": "METER", "pkt": "PACK", "packet": "PACK",
}


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
        } | UNIT_SYNONYMS


DISPLAY_KEYS = ("store_code", "sku", "name", "category", "store_price", "brand", "unit", "unit_value", "description")
_CURRENCY = re.compile(r"^(?:rs\.?|inr|₹|\$)\s*|\s*(?:/-|only)$", re.IGNORECASE)


def analyse(raw_rows, ignored_columns, *, mode, allow_image_urls, zip_images: ZipImages, check_urls=True,
            defaults=None, overrides=None, generate_sku=True) -> Analysis:
    """Validate every row.

    ``defaults`` fills a required column the file lacks (a user choice such as the store). ``overrides``
    ({row: {column: value}}) are the user's per-row corrections. The only automatic changes are the
    deterministic ones recorded in ``normalized`` / ``generated``; prices, tax, stock and legal data are
    never invented.
    """
    defaults = {k: v for k, v in (defaults or {}).items() if v}
    overrides = overrides or {}
    for raw in raw_rows:
        fixes = overrides.get(str(raw.number), {})
        for column, value in fixes.items():
            raw.values[column] = value if value not in ("",) else None
            raw.errors[:] = [(c, m) for c, m in raw.errors if c != column]
        for column, value in defaults.items():
            if not raw.values.get(column):
                raw.values[column] = value
    lookups = Lookups(raw_rows)
    seen = {}
    results = []
    for raw in raw_rows:
        result = RowResult(raw.number, errors=list(raw.errors))
        _validate_row(raw, result, lookups, mode, allow_image_urls, zip_images, seen, check_urls, generate_sku)
        result.values = {key: _text(raw.values.get(key)) for key in DISPLAY_KEYS}
        results.append(result)
    return Analysis(results, ignored_columns)


def _validate_row(raw, result, lookups, mode, allow_image_urls, zip_images, seen, check_urls, generate_sku=True):
    v, errors = raw.values, result.errors
    result.store_code = _text(v.get("store_code"))
    result.sku = _text(v.get("sku"))
    result.name = _text(v.get("name"))
    if not result.sku and result.name and generate_sku:
        # Deterministic, reversible and flagged: a slug of the name. Not a barcode.
        result.sku = ("AUTO-" + slugify(result.name).upper())[:64]
        v["sku"] = result.sku
        result.generated["sku"] = result.sku
    price = v.get("store_price")
    if isinstance(price, str):
        cleaned = _CURRENCY.sub("", price.strip()).strip()
        if cleaned != price:
            result.normalized["store_price"] = [price, cleaned]
            v["store_price"] = cleaned
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
