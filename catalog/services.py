import secrets
import string
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from accounts.audit_ip import get_client_ip
from accounts.models import AdminAuditLog

from .models import (
    Product,
    ProductImage,
    ProductPriceHistory,
    ProductStatus,
    ProductStatusHistory,
)
from .pricing import (
    apply_calculated_prices,
    calculate_prices,
    quantize_money,
)
from .status import (
    apply_approval_metadata,
    clear_approval_metadata,
    validate_product_for_approval,
    validate_status_transition,
)

PRODUCT_CODE_PREFIX = "PR"
PRODUCT_CODE_LENGTH = 8
PRODUCT_CODE_ALPHABET = string.ascii_uppercase + string.digits
PRODUCT_CODE_MAX_ATTEMPTS = 32

PRICING_FIELDS = (
    "store_price",
    "profit_margin_type",
    "profit_margin",
    "selling_price",
    "discount_type",
    "discount_value",
    "final_price",
)

# Catalogue edits that require admin re-review of an APPROVED product.
FIELDS_REQUIRING_REAPPROVAL = frozenset(
    {
        "name",
        "sku",
        "category",
        "brand",
        "description",
        "unit",
        "unit_value",
        "store_price",
        "manufacturing_date",
        "expiry_date",
    }
)

# Inventory balance is never catalogue-editable; only low-stock threshold is.
FIELDS_EXEMPT_FROM_REAPPROVAL = frozenset(
    {
        "low_stock_threshold",
    }
)


def _strip_direct_stock_quantity(product_data):
    """
    Drop stock_quantity from catalogue write payloads.

    Opening / purchase / adjustment stock must go through inventory.services so
    every change creates an immutable InventoryTransaction.
    """
    if not isinstance(product_data, dict):
        return product_data
    if "stock_quantity" not in product_data:
        return product_data
    cleaned = dict(product_data)
    cleaned.pop("stock_quantity", None)
    return cleaned


def _low_stock_q():
    """Products with stock remaining but at or below the low-stock threshold."""
    return Q(stock_quantity__gt=0) & Q(stock_quantity__lte=F("low_stock_threshold"))


def get_product_dashboard_stats(*, store=None):
    """
    Return product catalogue counts in one aggregate query.

    When ``store`` is provided, counts are limited to that store only.
    """
    queryset = Product.objects.all()
    if store is not None:
        queryset = queryset.filter(store_id=store.pk)
    return queryset.aggregate(
        total=Count("id"),
        draft=Count("id", filter=Q(status=ProductStatus.DRAFT)),
        pending=Count("id", filter=Q(status=ProductStatus.PENDING)),
        approved=Count("id", filter=Q(status=ProductStatus.APPROVED)),
        rejected=Count("id", filter=Q(status=ProductStatus.REJECTED)),
        low_stock=Count("id", filter=_low_stock_q()),
    )


def get_store_product_dashboard_stats(store):
    """Store-portal product card counts, scoped to the logged-in store."""
    return get_product_dashboard_stats(store=store)


def _candidate_product_code():
    token = "".join(
        secrets.choice(PRODUCT_CODE_ALPHABET) for _ in range(PRODUCT_CODE_LENGTH)
    )
    return f"{PRODUCT_CODE_PREFIX}{token}"


def generate_product_code(*, exclude_pk=None):
    """
    Return a product code that is not currently used.

    Concurrent inserts are protected by the unique constraint on Product.product_code;
    Product.save() retries on IntegrityError when allocating a new code.
    """
    for _ in range(PRODUCT_CODE_MAX_ATTEMPTS):
        code = _candidate_product_code()
        queryset = Product.objects.filter(product_code=code)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return code
    raise RuntimeError(
        "Unable to generate a unique product code after multiple attempts."
    )


def log_product_audit(
    *,
    actor,
    action,
    description,
    request=None,
    target_user=None,
    metadata=None,
    ip_address=None,
):
    resolved_ip = ip_address
    if resolved_ip is None and request is not None:
        resolved_ip = get_client_ip(request)
    safe_metadata = {
        key: value
        for key, value in (metadata or {}).items()
        if key.lower() not in {"password", "confirm_password", "temporary_password"}
    }
    return AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        target_user=target_user,
        description=description,
        metadata=safe_metadata,
        ip_address=resolved_ip,
    )


def portal_products_queryset(request):
    """Product queryset strictly limited to the caller's assigned store."""
    store = getattr(request, "store", None)
    if store is None:
        return Product.objects.none()
    return (
        Product.objects.filter(store_id=store.pk)
        .select_related("category", "brand", "store")
        .prefetch_related("tags", "images")
    )


def get_portal_product_or_404(request, pk):
    """Fetch a product for portal use; foreign store products raise Http404."""
    return get_object_or_404(portal_products_queryset(request), pk=pk)


def _snapshot_price_history(*, product, changed_by, reason="", request=None, ip_address=None):
    return ProductPriceHistory.objects.create(
        product=product,
        store_price=product.store_price,
        profit_margin_type=product.profit_margin_type or "",
        profit_margin=product.profit_margin,
        selling_price=product.selling_price,
        discount_type=product.discount_type or "",
        discount_value=product.discount_value,
        final_price=product.final_price,
        changed_by=changed_by,
        reason=(reason or "").strip(),
        ip_address=ip_address
        if ip_address is not None
        else (get_client_ip(request) if request is not None else None),
    )


def _pricing_tuple(product):
    return tuple(getattr(product, field) for field in PRICING_FIELDS)


def _relation_id(value):
    if value is None:
        return None
    return getattr(value, "pk", value)


def _normalize_comparable(field, value):
    if field in {"category", "brand"}:
        return _relation_id(value)
    if field in {
        "store_price",
        "unit_value",
        "stock_quantity",
        "low_stock_threshold",
        "profit_margin",
        "discount_value",
        "selling_price",
        "final_price",
    }:
        if value is None:
            return None
        return Decimal(str(value))
    if field == "description":
        return (value or "").strip()
    return value


def catalogue_field_changed(product, field, new_value):
    """Return True when a catalogue field value differs from the product's current value."""
    if field in {"category", "brand"}:
        old_value = getattr(product, f"{field}_id")
    else:
        old_value = getattr(product, field)
    return _normalize_comparable(field, old_value) != _normalize_comparable(
        field, new_value
    )


def changes_require_reapproval(product, product_data):
    """
    True when product_data includes a review-sensitive catalogue change.

    Stock quantity and low-stock threshold never require reapproval.
    """
    for field, value in product_data.items():
        if field in FIELDS_EXEMPT_FROM_REAPPROVAL:
            continue
        if field not in FIELDS_REQUIRING_REAPPROVAL:
            continue
        if catalogue_field_changed(product, field, value):
            return True
    return False


def changed_reapproval_fields(product, product_data):
    """Return the list of review-sensitive fields that actually changed."""
    changed = []
    for field, value in product_data.items():
        if field not in FIELDS_REQUIRING_REAPPROVAL:
            continue
        if catalogue_field_changed(product, field, value):
            changed.append(field)
    return changed


def record_resubmission_status_change(
    *,
    product,
    old_status,
    changed_by,
    changed_fields=None,
    request=None,
):
    """
    Persist APPROVED → PENDING history after a review-sensitive catalogue edit.

    Caller must already set product.status to PENDING and save the product.
    Previous admin pricing on the product instance is left intact.
    """
    fields = list(changed_fields or [])
    reason = "Returned to pending after catalogue edit requiring admin review"
    if fields:
        reason = f"{reason}: {', '.join(fields)}"

    history = ProductStatusHistory.objects.create(
        product=product,
        old_status=old_status,
        new_status=ProductStatus.PENDING,
        changed_by=changed_by,
        reason=reason,
        ip_address=get_client_ip(request) if request is not None else None,
    )
    log_product_audit(
        actor=changed_by,
        action=AdminAuditLog.Action.PRODUCT_STATUS_CHANGED,
        description=(
            f"Changed product '{product.product_code}' status "
            f"from {old_status} to {ProductStatus.PENDING}."
        ),
        request=request,
        ip_address=history.ip_address,
        metadata={
            "product_id": product.pk,
            "product_code": product.product_code,
            "old_status": old_status,
            "new_status": ProductStatus.PENDING,
            "reason": reason,
            "reapproval_fields": fields,
        },
    )
    return history


@transaction.atomic
def create_product(
    *,
    store,
    product_data,
    created_by,
    tag_ids=None,
    images=(),
    initial_status=ProductStatus.DRAFT,
    request=None,
):
    product_data = _strip_direct_stock_quantity(product_data)
    cleaned = {
        key: value
        for key, value in product_data.items()
        if key
        not in {
            "selling_price",
            "final_price",
            "profit_margin_type",
            "profit_margin",
            "discount_type",
            "discount_value",
            "status",
            "store",
            "product_code",
            "tags",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "stock_quantity",
        }
    }
    # Management create may set is_featured via cleaned data; store portal must not.
    # is_active defaults on the model unless explicitly provided by management.
    # stock_quantity always starts at 0; use inventory services for stock-in.
    product = Product(
        store=store,
        created_by=created_by,
        updated_by=created_by,
        status=initial_status,
        stock_quantity=Decimal("0.000"),
        **cleaned,
    )
    apply_calculated_prices(product)
    product.full_clean()
    product.save()

    if tag_ids is not None:
        product.tags.set(tag_ids)

    ProductStatusHistory.objects.create(
        product=product,
        old_status="",
        new_status=product.status,
        changed_by=created_by,
        reason="Product created",
        ip_address=get_client_ip(request) if request is not None else None,
    )
    _snapshot_price_history(
        product=product,
        changed_by=created_by,
        reason="Product created",
        request=request,
    )
    log_product_audit(
        actor=created_by,
        action=AdminAuditLog.Action.PRODUCT_CREATED,
        description=f"Created product '{product.product_code}'.",
        request=request,
        metadata={
            "product_id": product.pk,
            "product_code": product.product_code,
            "store_id": store.pk,
            "status": product.status,
        },
    )
    mutate_product_images(
        mutations={product.pk: {"add": [
            {"image": image, "sort_order": index}
            for index, image in enumerate(images)
        ]}},
        changed_by=created_by,
        request=request,
    )
    return product


@transaction.atomic
def update_product(
    *,
    product,
    product_data,
    updated_by,
    tag_ids=None,
    request=None,
    actor_is_store_user=False,
    force_pending_on_approved_edit=True,
):
    """
    Update catalogue fields and store_price.

    Store users cannot change management pricing or approval fields.
    Review-sensitive edits to an APPROVED product return it to PENDING while
    preserving prior admin pricing. Low-stock threshold changes alone do not
    require reapproval. stock_quantity is ignored here — use inventory services.

    Reloads the product from the database first so callers that pass a
    ModelForm-mutated instance still get correct change detection and
    preserved pricing.
    """
    product_data = _strip_direct_stock_quantity(product_data)
    forbidden_for_store = {
        "profit_margin_type",
        "profit_margin",
        "selling_price",
        "discount_type",
        "discount_value",
        "final_price",
        "status",
        "store",
        "product_code",
        "is_featured",
        "is_active",
        "rejection_reason",
        "stock_quantity",
    }
    if not product.pk:
        raise ValidationError("Cannot update a product that has not been saved.")

    # ModelForm.is_valid() mutates instance (and may recalculate prices via
    # Product.clean). Always compare and preserve against the DB row.
    product = Product.objects.select_for_update().get(pk=product.pk)
    old_pricing = _pricing_tuple(product)
    old_status = product.status
    requires_review = False
    review_fields = []

    if (
        actor_is_store_user
        and force_pending_on_approved_edit
        and old_status == ProductStatus.APPROVED
    ):
        requires_review = changes_require_reapproval(product, product_data)
        if requires_review:
            review_fields = changed_reapproval_fields(product, product_data)
        if tag_ids is not None:
            current_tag_ids = set(product.tags.values_list("pk", flat=True))
            new_tag_ids = {int(tag_id) for tag_id in tag_ids}
            if current_tag_ids != new_tag_ids:
                requires_review = True
                if "tags" not in review_fields:
                    review_fields.append("tags")

    preserved_pricing = {
        "profit_margin_type": product.profit_margin_type,
        "profit_margin": product.profit_margin,
        "selling_price": product.selling_price,
        "discount_type": product.discount_type,
        "discount_value": product.discount_value,
        "final_price": product.final_price,
    }

    for key, value in product_data.items():
        if key in {"tags", "store", "product_code", "status", "stock_quantity"}:
            continue
        if actor_is_store_user and key in forbidden_for_store:
            continue
        if key in {"selling_price", "final_price"}:
            continue
        setattr(product, key, value)

    if requires_review:
        # Keep previously approved selling/final/margin until admin re-reviews.
        # Product.clean() normally recalculates; freeze that path for this save.
        for key, value in preserved_pricing.items():
            setattr(product, key, value)
        product.status = ProductStatus.PENDING
        product.rejection_reason = ""
        product._freeze_calculated_prices = True
    else:
        apply_calculated_prices(product)

    product.updated_by = updated_by
    product.full_clean()
    if requires_review:
        for key, value in preserved_pricing.items():
            setattr(product, key, value)
    product.save()
    if hasattr(product, "_freeze_calculated_prices"):
        delattr(product, "_freeze_calculated_prices")

    if tag_ids is not None:
        product.tags.set(tag_ids)

    if requires_review and old_status == ProductStatus.APPROVED:
        record_resubmission_status_change(
            product=product,
            old_status=old_status,
            changed_by=updated_by,
            changed_fields=review_fields,
            request=request,
        )

    if _pricing_tuple(product) != old_pricing:
        price_reason = (
            "Store price updated; admin pricing preserved pending reapproval"
            if requires_review
            else "Product pricing fields updated"
        )
        _snapshot_price_history(
            product=product,
            changed_by=updated_by,
            reason=price_reason,
            request=request,
        )
        log_product_audit(
            actor=updated_by,
            action=AdminAuditLog.Action.PRODUCT_PRICING_CHANGED,
            description=f"Updated pricing for product '{product.product_code}'.",
            request=request,
            metadata={
                "product_id": product.pk,
                "product_code": product.product_code,
                "store_price": str(product.store_price),
                "final_price": (
                    str(product.final_price) if product.final_price is not None else None
                ),
                "admin_pricing_preserved": requires_review,
            },
        )

    log_product_audit(
        actor=updated_by,
        action=AdminAuditLog.Action.PRODUCT_UPDATED,
        description=f"Updated product '{product.product_code}'.",
        request=request,
        metadata={
            "product_id": product.pk,
            "product_code": product.product_code,
            "status": product.status,
            "requires_reapproval": requires_review,
            "reapproval_fields": review_fields,
        },
    )
    return product


@transaction.atomic
def apply_admin_pricing(
    *,
    product,
    profit_margin_type,
    profit_margin,
    discount_type="",
    discount_value=None,
    changed_by,
    reason="",
    request=None,
):
    """
    Set admin margin/discount fields and recompute selling/final prices.

    Browser-submitted selling/final values are never accepted. History is
    written only when pricing fields actually change.
    """
    Product.objects.select_for_update().get(pk=product.pk)
    product.refresh_from_db()
    old_pricing = _pricing_tuple(product)

    discount_type = discount_type or ""
    if discount_value is None:
        discount_value = Decimal("0.00")
    profit_margin = quantize_money(profit_margin)
    discount_value = quantize_money(discount_value)

    selling, final = calculate_prices(
        store_price=product.store_price,
        profit_margin_type=profit_margin_type,
        profit_margin=profit_margin,
        discount_type=discount_type,
        discount_value=discount_value,
    )
    product.profit_margin_type = profit_margin_type
    product.profit_margin = profit_margin
    product.discount_type = discount_type
    product.discount_value = discount_value
    product.selling_price = selling
    product.final_price = final
    product.updated_by = changed_by
    product.full_clean()
    product.save(
        update_fields=[
            "profit_margin_type",
            "profit_margin",
            "discount_type",
            "discount_value",
            "selling_price",
            "final_price",
            "updated_by",
            "updated_at",
        ]
    )

    if _pricing_tuple(product) != old_pricing:
        _snapshot_price_history(
            product=product,
            changed_by=changed_by,
            reason=(reason or "").strip() or "Admin pricing updated",
            request=request,
        )
        log_product_audit(
            actor=changed_by,
            action=AdminAuditLog.Action.PRODUCT_PRICING_CHANGED,
            description=f"Set admin pricing for product '{product.product_code}'.",
            request=request,
            metadata={
                "product_id": product.pk,
                "product_code": product.product_code,
                "selling_price": str(product.selling_price),
                "final_price": str(product.final_price),
                "profit_margin_type": product.profit_margin_type,
                "discount_type": product.discount_type,
                "reason": (reason or "").strip(),
            },
        )
    return product


@transaction.atomic
def record_product_status_change(
    *,
    product,
    new_status,
    changed_by,
    reason="",
    request=None,
    actor_is_store_user=False,
):
    """
    Apply an allowed status transition, record history, and update approval metadata.

    Approval stamps approved_by / approved_at. Leaving APPROVED (reject, inactive,
    or resubmit to PENDING) clears those fields. Rejection always stores a reason.
    """
    Product.objects.select_for_update().get(pk=product.pk)
    product.refresh_from_db()
    old_status = product.status
    validate_status_transition(
        current_status=old_status,
        new_status=new_status,
        reason=reason,
        product=product,
        actor_is_store_user=actor_is_store_user,
    )
    product.status = new_status
    update_fields = ["status", "rejection_reason", "updated_by", "updated_at"]

    if new_status == ProductStatus.REJECTED:
        product.rejection_reason = (reason or "").strip()
        clear_approval_metadata(product)
        update_fields.extend(["approved_by", "approved_at"])
    elif new_status == ProductStatus.APPROVED:
        product.rejection_reason = ""
        apply_approval_metadata(product, approved_by=changed_by)
        update_fields.extend(["approved_by", "approved_at"])
    elif old_status == ProductStatus.APPROVED:
        # Deactivate or return to pending — no longer an approved listing.
        clear_approval_metadata(product)
        update_fields.extend(["approved_by", "approved_at"])

    product.updated_by = changed_by
    product.save(update_fields=update_fields)
    history = ProductStatusHistory.objects.create(
        product=product,
        old_status=old_status,
        new_status=new_status,
        changed_by=changed_by,
        reason=(reason or "").strip(),
        ip_address=get_client_ip(request) if request is not None else None,
    )
    log_product_audit(
        actor=changed_by,
        action=AdminAuditLog.Action.PRODUCT_STATUS_CHANGED,
        description=(
            f"Changed product '{product.product_code}' status "
            f"from {old_status or '—'} to {new_status}."
        ),
        request=request,
        ip_address=history.ip_address,
        metadata={
            "product_id": product.pk,
            "product_code": product.product_code,
            "old_status": old_status,
            "new_status": new_status,
            "reason": history.reason,
            "approved_by_id": (
                product.approved_by_id if new_status == ProductStatus.APPROVED else None
            ),
        },
    )
    return product


@transaction.atomic
def mutate_product_images(*, mutations, changed_by=None, request=None, validate_only=False):
    """Apply complete per-product image batches under ordered parent locks.

    Each batch has add (field dictionaries), update (ID -> field dictionaries)
    and delete (IDs). Storage writes are not transactional: failed transactions
    deliberately leave uploaded objects for future delayed orphan cleanup.
    Callers remain responsible for authorization; image IDs are parent-scoped.
    """
    from .validators import MAX_IMAGES_PER_PRODUCT

    products = list(Product.objects.select_for_update().filter(
        pk__in=mutations,
    ).order_by("pk"))
    if len(products) != len(mutations):
        raise ValidationError("Product no longer exists.")
    prepared = []
    allowed_fields = {"image", "alt_text", "sort_order", "is_primary"}
    # Validate every batch before making any database or storage writes.
    for product in products:
        batch = mutations[product.pk]
        additions = batch.get("add", [])
        updates = batch.get("update", {})
        existing = {obj.pk: obj for obj in product.images.order_by("sort_order", "pk")}
        deletions = set(existing) if batch.get("delete_all") else set(batch.get("delete", []))
        if (set(updates) | deletions) - existing.keys():
            raise Http404("Product image not found.")
        if set(updates) & deletions:
            raise ValidationError("Invalid product image selection.")
        final_count = len(existing) + len(additions) - len(deletions)
        if final_count > MAX_IMAGES_PER_PRODUCT:
            raise ValidationError(f"A product may have at most {MAX_IMAGES_PER_PRODUCT} images.")
        if deletions and product.status == ProductStatus.APPROVED and final_count < 1:
            raise ValidationError("Approved products must keep at least one image.")
        for fields in [*additions, *updates.values()]:
            if set(fields) - allowed_fields:
                raise ValidationError("Invalid product image fields.")
        prepared.append((product, additions, updates, deletions, existing))

    if validate_only:
        return
    results = {}
    for product, additions, updates, deletions, existing in prepared:
        if not (additions or updates or deletions):
            results[product.pk] = []
            continue
        primary_id = next((pk for pk, obj in existing.items() if obj.is_primary), None)
        primary = existing.get(primary_id) if primary_id not in deletions else None
        ProductImage.objects.filter(product=product, is_primary=True).update(is_primary=False)
        # Model deletion removes references only, never the underlying object.
        ProductImage.objects.filter(product=product, pk__in=deletions).delete()
        saved = []
        binary_changed = bool(additions or deletions)
        for pk, fields in updates.items():
            obj = existing[pk]
            obj.is_primary = False
            for name, value in fields.items():
                if name != "is_primary":
                    setattr(obj, name, value)
            binary_changed |= "image" in fields
            if fields.get("is_primary"):
                primary = obj
            elif fields.get("is_primary") is False and primary is obj:
                primary = None
            # Metadata-only edits need not open the stored image.
            obj.full_clean(exclude=[] if "image" in fields else ["image"])
            obj.save()
            saved.append(obj)
        for fields in additions:
            obj = ProductImage(product=product, **{k: v for k, v in fields.items() if k != "is_primary"})
            obj.full_clean()
            obj.save()
            if fields.get("is_primary"):
                primary = obj
            saved.append(obj)
        if primary is None:
            primary = product.images.order_by("sort_order", "pk").first()
        if primary is not None:
            ProductImage.objects.filter(pk=primary.pk).update(is_primary=True)
        for obj in saved:
            obj.is_primary = primary is not None and obj.pk == primary.pk
        if binary_changed and product.status == ProductStatus.APPROVED:
            record_product_status_change(
                product=product, new_status=ProductStatus.PENDING,
                changed_by=changed_by, reason="Product images changed; reapproval required.",
                request=request,
            )
        results[product.pk] = saved
    return results


def add_product_image(*, product, image, alt_text="", sort_order=0,
                      is_primary=False, changed_by=None, request=None):
    return mutate_product_images(mutations={product.pk: {"add": [{
        "image": image, "alt_text": alt_text, "sort_order": sort_order,
        "is_primary": is_primary,
    }]}}, changed_by=changed_by, request=request)[product.pk][0]


def replace_product_image(*, product, image_id, image, changed_by=None, request=None):
    return mutate_product_images(mutations={product.pk: {"update": {
        image_id: {"image": image},
    }}}, changed_by=changed_by, request=request)[product.pk][0]


def set_primary_product_image(*, product, image_id):
    return mutate_product_images(mutations={product.pk: {"update": {
        image_id: {"is_primary": True},
    }}})[product.pk][0]


def delete_product_image(*, product, image_id, changed_by=None, request=None):
    mutate_product_images(mutations={product.pk: {"delete": [image_id]}},
                          changed_by=changed_by, request=request)


def guard_product_image_cascade(products):
    """Use the same complete-deletion validation before admin parent cascades.

    The caller owns the transaction and performs the parent deletion immediately
    afterwards. Validate without deleting images or creating transient history.
    """
    mutate_product_images(mutations={product.pk: {"delete_all": True}
                                    for product in products}, validate_only=True)


def assert_pricing_complete_for_approval(product):
    """Backward-compatible alias for full approval requirement checks."""
    validate_product_for_approval(product)
