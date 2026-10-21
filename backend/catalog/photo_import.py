"""Permission-checked import boundary shared by the website and CLI."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from inventory.services import record_opening_stock
from stores.models import Store, StoreStatus
from .decorators import user_has_catalog_permission
from .models import (
    Brand,
    PhotoImportItem,
    Product,
    ProductCategory,
    ProductStatus,
    ProductUnit,
)
from .pricing import MarginType
from .services import create_product, apply_admin_pricing, record_product_status_change


class ImportReviewForm(forms.Form):
    name = forms.CharField(max_length=200)
    description = forms.CharField(required=False, max_length=8000)
    category = forms.ModelChoiceField(
        queryset=ProductCategory.objects.filter(is_active=True)
    )
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.filter(is_active=True), required=False
    )
    unit = forms.ChoiceField(choices=ProductUnit.choices, initial=ProductUnit.PIECE)
    unit_value = forms.DecimalField(
        min_value=Decimal("0.001"), max_digits=12, decimal_places=3, initial=1
    )
    store_price = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=12, decimal_places=2, required=False
    )
    pricing_policy = forms.ChoiceField(
        choices=[
            ("retail_mean", "Use researched average; no extra margin"),
            ("manual", "Use my Store Price; no extra margin"),
        ]
    )
    stock = forms.DecimalField(
        min_value=Decimal("0.001"), max_digits=12, decimal_places=3, required=False
    )
    identity_verified = forms.BooleanField(required=True)
    offers_verified = forms.BooleanField(required=False)
    notes = forms.CharField(required=False, max_length=4000)


def require_permissions(actor, *permissions):
    if not all(user_has_catalog_permission(actor, p) for p in permissions):
        raise PermissionDenied("Your account needs permission for this import action.")


def price_research(offers):
    if not isinstance(offers, list) or len(offers) > 10:
        raise ValidationError("Provide up to ten comparable retailer offers.")
    values, normalized, domains = [], [], set()
    for offer in offers:
        if not isinstance(offer, dict):
            raise ValidationError("Each offer must contain a URL, price and date.")
        url = str(offer.get("url", "")).strip()
        URLValidator(schemes=["https"])(url)
        domain = urlsplit(url).hostname.lower().removeprefix("www.")
        if domain in domains:
            raise ValidationError("Use only one offer from each independent retailer.")
        domains.add(domain)
        try:
            price = Decimal(str(offer.get("price", "")))
            checked = date.fromisoformat(str(offer.get("checked_at", "")))
        except (InvalidOperation, ValueError):
            raise ValidationError("Each offer needs a valid price and check date.")
        if (
            not price.is_finite()
            or not Decimal("0") < price < Decimal("1000000000")
            or price.as_tuple().exponent < -2
        ):
            raise ValidationError(
                "Offer prices must be positive INR amounts with at most two decimals."
            )
        if checked > timezone.localdate() or (timezone.localdate() - checked).days > 30:
            raise ValidationError(
                "Recheck offers older than 30 days; future dates are invalid."
            )
        if (
            offer.get("currency", "INR") != "INR"
            or offer.get("availability") != "in_stock"
            or offer.get("exact_match") is not True
        ):
            raise ValidationError(
                "Only exact-match, in-stock INR offers qualify for this average."
            )
        values.append(price)
        normalized.append(
            {
                "url": url,
                "price": str(price),
                "checked_at": checked.isoformat(),
                "retailer": domain,
                "currency": "INR",
                "availability": "in_stock",
                "exact_match": True,
                "tax_shipping": str(offer.get("tax_shipping", "Not confirmed"))[:500],
            }
        )
    if not values:
        return {"count": 0, "offers": []}
    values.sort()
    n = len(values)
    money = lambda v: str(v.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    return {
        "count": n,
        "mean": money(sum(values) / n),
        "median": money((values[(n - 1) // 2] + values[n // 2]) / 2),
        "min": money(values[0]),
        "max": money(values[-1]),
        "offers": normalized,
        "label": "Sampled online price estimate",
        "limited_sources": n < 3,
    }


def validated_item(item):
    form = ImportReviewForm(item.details)
    if not form.is_valid():
        raise ValidationError({k: [str(e) for e in v] for k, v in form.errors.items()})
    data = form.cleaned_data
    research = price_research(item.details.get("offers", []))
    if data["pricing_policy"] == "retail_mean":
        if not research["count"] or not data["offers_verified"]:
            raise ValidationError(
                "Verify at least one exact-match retailer offer before using its average."
            )
        price = Decimal(research["mean"])
    else:
        price = data["store_price"]
        if price is None:
            raise ValidationError(
                "Enter your actual Store Price or select the researched average policy."
            )
    if not 1 <= item.photos.filter(selected=True).count() <= 5:
        raise ValidationError("Select between one and five listing photos.")
    return data, research, price


@transaction.atomic
def import_item(*, item_id, actor, publish=False, dry_run=False, request=None):
    require_permissions(actor, "catalog.add_product", "catalog.manage_product_pricing")
    if publish:
        require_permissions(actor, "catalog.approve_product")
    item = (
        PhotoImportItem.objects.select_for_update()
        .select_related("batch")
        .get(pk=item_id)
    )
    if item.batch.created_by_id != actor.pk and not actor.is_superuser:
        raise PermissionDenied("This import belongs to another administrator.")
    if item.product_id:
        return {"state": "already_imported", "product_id": item.product_id}
    if not item.batch.store_id:
        raise ValidationError("Select a destination Store before importing.")
    store = Store.objects.select_for_update().get(pk=item.batch.store_id)
    if not store.is_active or store.status != StoreStatus.ACTIVE:
        raise ValidationError("The destination Store must be active.")
    data, research, price = validated_item(item)
    if data["stock"] is not None:
        require_permissions(actor, "inventory.adjust_inventory")
    sku = "ZI-" + item.source_hash[:32].upper()
    existing = Product.objects.filter(store=store, sku=sku).first()
    if existing:
        # A stable source fingerprint is an idempotency key, never an update policy.
        if not dry_run:
            item.product = existing
            item.imported_at = timezone.now()
            item.save(update_fields=["product", "imported_at", "updated_at"])
        return {"state": "existing_product", "product_id": existing.pk}
    result = {
        "state": "ready",
        "sku": sku,
        "store_price": str(price),
        "final_price": str(price),
        "research": research,
        "stock": str(data["stock"]) if data["stock"] is not None else "0.000",
        "status": ProductStatus.APPROVED if publish else ProductStatus.PENDING,
    }
    product_data = {
        k: data[k]
        for k in ("name", "description", "category", "brand", "unit", "unit_value")
    }
    product_data.update(sku=sku, store_price=price)
    candidate = Product(store=store, **product_data)
    candidate.full_clean(exclude=["product_code"])
    if dry_run:
        return result
    # Media already exists in private staging. Reusing its storage reference avoids
    # non-transactional copy writes and orphan files if approval/stock fails later.
    product = create_product(
        store=store,
        product_data=product_data,
        created_by=actor,
        initial_status=ProductStatus.PENDING,
        request=request,
    )
    from .services import mutate_product_images

    mutate_product_images(
        mutations={
            product.pk: {
                "add": [
                    {"image": photo.image.name, "sort_order": index}
                    for index, photo in enumerate(item.photos.filter(selected=True))
                ]
            }
        },
        changed_by=actor,
        request=request,
    )
    reason = "Photo import %s / %s; %s" % (
        item.batch_id,
        item.source_key,
        data["pricing_policy"],
    )
    apply_admin_pricing(
        product=product,
        profit_margin_type=MarginType.FIXED,
        profit_margin=Decimal("0"),
        changed_by=actor,
        reason=reason,
        request=request,
    )
    if data["stock"] is not None:
        record_opening_stock(
            product=product,
            store=store,
            quantity=data["stock"],
            actor=actor,
            reason=reason,
            request=request,
        )
    if publish:
        record_product_status_change(
            product=product,
            new_status=ProductStatus.APPROVED,
            changed_by=actor,
            reason=reason,
            request=request,
        )
    item.product = product
    item.imported_at = timezone.now()
    item.details = {**item.details, "research": research}
    item.save(update_fields=["product", "imported_at", "details", "updated_at"])
    result.update(state="published" if publish else "pending", product_id=product.pk)
    return result
