import secrets
import string
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.audit_ip import get_client_ip
from catalog.models import Product
from catalog.pricing import quantize_money

from .models import (
    REASON_REQUIRED_TYPES,
    TRANSACTION_TYPE_DIRECTION,
    InventoryDirection,
    InventoryTransaction,
    InventoryTransactionType,
    PurchaseEntry,
    PurchaseEntryLine,
    PurchaseEntryStatus,
    validate_manufacturing_and_expiry_dates,
)

TRANSACTION_NUMBER_PREFIX = "TX"
PURCHASE_ENTRY_NUMBER_PREFIX = "PE"
NUMBER_DATE_FORMAT = "%Y%m%d"
NUMBER_TOKEN_LENGTH = 8
NUMBER_ALPHABET = string.ascii_uppercase + string.digits
TRANSACTION_NUMBER_MAX_ATTEMPTS = 32
ENTRY_NUMBER_MAX_ATTEMPTS = 32

# Immutable ledger references for order stock movements. Unique among
# InventoryTransaction.reference values that use this prefix (DB constraint).
ORDER_ITEM_REFERENCE_PREFIX = "order-item:"
ORDER_ITEM_DEDUCT_SUFFIX = ":deduct"
ORDER_ITEM_RESTORE_SUFFIX = ":restore"

THREEPLACES = Decimal("0.001")


def order_item_deduct_reference(order_item_id) -> str:
    """Stable reference for the single checkout STOCK_OUT of an OrderItem."""
    return f"{ORDER_ITEM_REFERENCE_PREFIX}{order_item_id}{ORDER_ITEM_DEDUCT_SUFFIX}"


def order_item_restore_reference(order_item_id) -> str:
    """Stable reference for the single cancel/reject CUSTOMER_RETURN of an OrderItem."""
    return f"{ORDER_ITEM_REFERENCE_PREFIX}{order_item_id}{ORDER_ITEM_RESTORE_SUFFIX}"


def _find_transaction_by_reference(reference):
    if not (reference or "").strip():
        return None
    return (
        InventoryTransaction.objects.select_related("product", "store")
        .filter(reference=reference)
        .first()
    )


def _require_order_reference(reference):
    cleaned = (reference or "").strip()
    if not cleaned.startswith(ORDER_ITEM_REFERENCE_PREFIX):
        raise ValidationError(
            {
                "reference": (
                    "Order inventory movements require an immutable "
                    f"'{ORDER_ITEM_REFERENCE_PREFIX}…' reference."
                )
            }
        )
    return cleaned


def _assert_existing_order_txn_matches(
    *,
    existing,
    product,
    store,
    quantity,
    transaction_type,
):
    """Reject reuse of a reference that points at a different movement."""
    quantity = quantize_quantity(quantity)
    errors = {}
    if existing.product_id != getattr(product, "pk", product):
        errors["reference"] = "Reference already used for a different product."
    if existing.store_id != getattr(store, "pk", store):
        errors["reference"] = "Reference already used for a different store."
    if existing.transaction_type != transaction_type:
        errors["reference"] = "Reference already used for a different movement type."
    if quantize_quantity(existing.quantity) != quantity:
        errors["reference"] = "Reference already used for a different quantity."
    if errors:
        raise ValidationError(errors)


def _as_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_quantity(value):
    return _as_decimal(value).quantize(THREEPLACES)


def _candidate_number(prefix):
    date_part = timezone.localdate().strftime(NUMBER_DATE_FORMAT)
    token = "".join(
        secrets.choice(NUMBER_ALPHABET) for _ in range(NUMBER_TOKEN_LENGTH)
    )
    return f"{prefix}-{date_part}-{token}"


def generate_transaction_number(*, exclude_pk=None):
    for _ in range(TRANSACTION_NUMBER_MAX_ATTEMPTS):
        number = _candidate_number(TRANSACTION_NUMBER_PREFIX)
        queryset = InventoryTransaction.objects.filter(transaction_number=number)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return number
    raise RuntimeError(
        "Unable to generate a unique inventory transaction number "
        "after multiple attempts."
    )


def generate_purchase_entry_number(*, exclude_pk=None):
    for _ in range(ENTRY_NUMBER_MAX_ATTEMPTS):
        number = _candidate_number(PURCHASE_ENTRY_NUMBER_PREFIX)
        queryset = PurchaseEntry.objects.filter(entry_number=number)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        if not queryset.exists():
            return number
    raise RuntimeError(
        "Unable to generate a unique purchase entry number after multiple attempts."
    )


def log_inventory_audit(
    *,
    actor,
    action,
    description,
    request=None,
    metadata=None,
    ip_address=None,
):
    from accounts.models import AdminAuditLog

    resolved_ip = ip_address
    if resolved_ip is None and request is not None:
        resolved_ip = get_client_ip(request)
    return AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        description=description,
        metadata=metadata or {},
        ip_address=resolved_ip,
    )


def _validate_positive_quantity(quantity):
    quantity = quantize_quantity(quantity)
    if quantity <= 0:
        raise ValidationError(
            {"quantity": "Movement quantity must be greater than zero."}
        )
    return quantity


def _validate_store_product(*, store, product):
    if product.store_id != store.pk:
        raise ValidationError(
            {"product": "Product must belong to the selected store."}
        )


def _require_reason(transaction_type, reason):
    if transaction_type in REASON_REQUIRED_TYPES and not (reason or "").strip():
        raise ValidationError(
            {"reason": "A reason is required for this stock movement."}
        )


def _signed_delta(direction, quantity):
    if direction == InventoryDirection.IN:
        return quantity
    if direction == InventoryDirection.OUT:
        return -quantity
    raise ValidationError({"direction": "Invalid inventory direction."})


def _create_transaction_row(**fields):
    """
    Persist a new InventoryTransaction.

    Callers must already be inside transaction.atomic() and hold a locked Product.
    """
    txn = InventoryTransaction(**fields)
    txn.full_clean()
    txn.save()
    return txn


@transaction.atomic
def apply_stock_movement(
    *,
    product,
    store,
    transaction_type,
    quantity,
    actor=None,
    reason="",
    notes="",
    reference="",
    unit_cost=None,
    manufacturing_date=None,
    expiry_date=None,
    purchase_entry=None,
    purchase_entry_line=None,
    ip_address=None,
    request=None,
    is_system_generated=False,
    skip_product_update=False,
):
    """
    Apply one stock movement under a row lock.

    On success: updates Product.stock_quantity (unless skip_product_update) and
    creates exactly one InventoryTransaction.

    On ValidationError or any other exception: the atomic block rolls back both
    the Product update and the transaction row.
    """
    quantity = _validate_positive_quantity(quantity)
    direction = TRANSACTION_TYPE_DIRECTION[transaction_type]
    _require_reason(transaction_type, reason)
    validate_manufacturing_and_expiry_dates(manufacturing_date, expiry_date)

    if unit_cost is not None:
        unit_cost = quantize_money(unit_cost)
        if unit_cost < 0:
            raise ValidationError({"unit_cost": "Unit cost cannot be negative."})

    locked_product = Product.objects.select_for_update().get(pk=product.pk)
    _validate_store_product(store=store, product=locked_product)

    if purchase_entry is not None and purchase_entry.store_id != store.pk:
        raise ValidationError(
            {"purchase_entry": "Purchase entry must belong to the selected store."}
        )

    if transaction_type == InventoryTransactionType.OPENING:
        if _opening_already_recorded(locked_product):
            raise ValidationError(
                {
                    "product": (
                        "Opening stock has already been recorded for this product."
                    )
                }
            )

    previous_quantity = quantize_quantity(locked_product.stock_quantity)
    delta = _signed_delta(direction, quantity)
    new_quantity = quantize_quantity(previous_quantity + delta)

    if not skip_product_update and new_quantity < 0:
        raise ValidationError(
            {
                "quantity": (
                    "Insufficient stock. Available "
                    f"{previous_quantity}, requested {quantity}."
                )
            }
        )

    resolved_ip = ip_address
    if resolved_ip is None and request is not None:
        resolved_ip = get_client_ip(request)

    if skip_product_update:
        # Represent existing balance in history without changing Product.
        if previous_quantity <= 0:
            raise ValidationError(
                {
                    "quantity": (
                        "Cannot convert opening stock when current balance is zero."
                    )
                }
            )
        if quantize_quantity(quantity) != previous_quantity:
            raise ValidationError(
                {
                    "quantity": (
                        "Conversion quantity must equal the product's current "
                        f"stock balance ({previous_quantity})."
                    )
                }
            )
        txn_previous = Decimal("0.000")
        txn_new = previous_quantity
        quantity = previous_quantity
    else:
        txn_previous = previous_quantity
        txn_new = new_quantity
        locked_product.stock_quantity = new_quantity
        locked_product.save(update_fields=["stock_quantity", "updated_at"])

    return _create_transaction_row(
        store=store,
        product=locked_product,
        transaction_type=transaction_type,
        direction=direction,
        quantity=quantity if not skip_product_update else previous_quantity,
        previous_quantity=txn_previous,
        new_quantity=txn_new,
        unit_cost=unit_cost,
        reference=reference or "",
        reason=(reason or "").strip(),
        notes=notes or "",
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        purchase_entry=purchase_entry,
        purchase_entry_line=purchase_entry_line,
        created_by=actor,
        ip_address=resolved_ip,
        is_system_generated=is_system_generated,
    )


def _opening_already_recorded(product):
    return InventoryTransaction.objects.filter(
        product_id=product.pk,
        transaction_type=InventoryTransactionType.OPENING,
    ).exists()


@transaction.atomic
def record_opening_stock(
    *,
    product,
    store,
    quantity,
    actor=None,
    reason="",
    notes="",
    reference="",
    manufacturing_date=None,
    expiry_date=None,
    ip_address=None,
    request=None,
):
    """Record opening stock as an IN movement. Allowed once per product."""
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.OPENING,
        quantity=quantity,
        actor=actor,
        reason=reason or "Opening stock",
        notes=notes,
        reference=reference,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def convert_existing_opening_stock(
    *,
    product,
    store,
    actor=None,
    reason="",
    notes="",
    reference="",
    ip_address=None,
    request=None,
    is_system_generated=True,
):
    """
    Preserve an existing Product.stock_quantity in the ledger without changing it.

    Creates one OPENING InventoryTransaction with previous_quantity=0 and
    new_quantity equal to the current balance.
    """
    locked = Product.objects.select_for_update().get(pk=product.pk)
    return apply_stock_movement(
        product=locked,
        store=store,
        transaction_type=InventoryTransactionType.OPENING,
        quantity=locked.stock_quantity,
        actor=actor,
        reason=reason or "Converted existing catalogue opening stock",
        notes=notes,
        reference=reference,
        ip_address=ip_address,
        request=request,
        is_system_generated=is_system_generated,
        skip_product_update=True,
    )


def products_needing_opening_stock_initialization():
    """
    Products with a positive balance and no inventory ledger history yet.

    Zero-stock products are excluded. Products that already have any
    InventoryTransaction (including OPENING) are excluded so the operation
    is safe to re-run.
    """
    products_with_history = InventoryTransaction.objects.values("product_id")
    return (
        Product.objects.filter(stock_quantity__gt=Decimal("0"))
        .exclude(pk__in=products_with_history)
        .select_related("store")
        .order_by("pk")
    )


def initialize_opening_stock_from_catalogue(*, actor=None, dry_run=False):
    """
    Idempotently create OPENING ledger rows for existing positive balances.

    Does not modify Product.stock_quantity. Safe to run repeatedly: products
    that already have inventory history are skipped.

    Returns a dict with counts: converted, skipped_zero_or_history, dry_run.
    """
    candidates = list(products_needing_opening_stock_initialization())
    converted = []

    if dry_run:
        return {
            "converted": 0,
            "candidate_count": len(candidates),
            "product_ids": [product.pk for product in candidates],
            "dry_run": True,
            "transactions": [],
        }

    for product in candidates:
        # Re-check under the conversion lock path; skip if history appeared.
        if product.inventory_transactions.exists():
            continue
        if product.stock_quantity <= 0:
            continue
        balance_before = product.stock_quantity
        txn = convert_existing_opening_stock(
            product=product,
            store=product.store,
            actor=actor,
            reason="Initialized opening stock from existing catalogue balance",
            is_system_generated=True,
        )
        product.refresh_from_db(fields=["stock_quantity"])
        if product.stock_quantity != balance_before:
            raise ValidationError(
                {
                    "stock_quantity": (
                        f"Opening initialization changed stock for product "
                        f"{product.pk}; aborting to protect production balances."
                    )
                }
            )
        converted.append(txn)

    return {
        "converted": len(converted),
        "candidate_count": len(candidates),
        "product_ids": [txn.product_id for txn in converted],
        "dry_run": False,
        "transactions": converted,
    }


@transaction.atomic
def record_manual_stock_in(
    *,
    product,
    store,
    quantity,
    actor=None,
    reason="",
    notes="",
    reference="",
    unit_cost=None,
    manufacturing_date=None,
    expiry_date=None,
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.STOCK_IN,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        unit_cost=unit_cost,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def record_manual_stock_out(
    *,
    product,
    store,
    quantity,
    actor,
    reason,
    notes="",
    reference="",
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.STOCK_OUT,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def record_adjustment_in(
    *,
    product,
    store,
    quantity,
    actor,
    reason,
    notes="",
    reference="",
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.ADJUSTMENT_IN,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def record_adjustment_out(
    *,
    product,
    store,
    quantity,
    actor,
    reason,
    notes="",
    reference="",
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.ADJUSTMENT_OUT,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def record_damaged_stock(
    *,
    product,
    store,
    quantity,
    actor,
    reason,
    notes="",
    reference="",
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.DAMAGED,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def record_expired_stock(
    *,
    product,
    store,
    quantity,
    actor,
    reason,
    notes="",
    reference="",
    manufacturing_date=None,
    expiry_date=None,
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.EXPIRED,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def record_customer_return(
    *,
    product,
    store,
    quantity,
    actor=None,
    reason="",
    notes="",
    reference="",
    unit_cost=None,
    manufacturing_date=None,
    expiry_date=None,
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        unit_cost=unit_cost,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        ip_address=ip_address,
        request=request,
    )


@transaction.atomic
def deduct_order_stock(
    *,
    product,
    store,
    quantity,
    reference,
    actor=None,
    reason="",
    notes="",
    ip_address=None,
    request=None,
):
    """
    Deduct sellable stock at checkout.

    Maps to existing STOCK_OUT (OUT). ``reference`` must be the immutable
    order-item deduct key from ``order_item_deduct_reference``; repeating the
    same reference returns the existing row and does not deduct again.
    """
    reference = _require_order_reference(reference)
    existing = _find_transaction_by_reference(reference)
    if existing is not None:
        _assert_existing_order_txn_matches(
            existing=existing,
            product=product,
            store=store,
            quantity=quantity,
            transaction_type=InventoryTransactionType.STOCK_OUT,
        )
        return existing

    try:
        with transaction.atomic():
            return apply_stock_movement(
                product=product,
                store=store,
                transaction_type=InventoryTransactionType.STOCK_OUT,
                quantity=quantity,
                actor=actor,
                reason=(reason or "").strip() or "Order stock deduction",
                notes=notes or "Stock deducted at checkout.",
                reference=reference,
                ip_address=ip_address,
                request=request,
                is_system_generated=True,
            )
    except IntegrityError:
        existing = _find_transaction_by_reference(reference)
        if existing is None:
            raise
        _assert_existing_order_txn_matches(
            existing=existing,
            product=product,
            store=store,
            quantity=quantity,
            transaction_type=InventoryTransactionType.STOCK_OUT,
        )
        return existing


@transaction.atomic
def restore_order_stock(
    *,
    product,
    store,
    quantity,
    reference,
    actor=None,
    reason="",
    notes="",
    ip_address=None,
    request=None,
):
    """
    Restore sellable stock previously deducted at checkout.

    Maps to existing CUSTOMER_RETURN (IN) for cancellation and store rejection.
    Does not delete or edit the original checkout STOCK_OUT — the ledger remains
    append-only. ``reference`` must be the immutable order-item restore key from
    ``order_item_restore_reference``; repeating it returns the existing row and
    does not restore again.
    """
    reference = _require_order_reference(reference)
    existing = _find_transaction_by_reference(reference)
    if existing is not None:
        _assert_existing_order_txn_matches(
            existing=existing,
            product=product,
            store=store,
            quantity=quantity,
            transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
        )
        return existing

    try:
        with transaction.atomic():
            return apply_stock_movement(
                product=product,
                store=store,
                transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
                quantity=quantity,
                actor=actor,
                reason=(reason or "").strip() or "Order stock restoration",
                notes=notes or "Stock restored after order cancel/reject.",
                reference=reference,
                ip_address=ip_address,
                request=request,
                is_system_generated=True,
            )
    except IntegrityError:
        existing = _find_transaction_by_reference(reference)
        if existing is None:
            raise
        _assert_existing_order_txn_matches(
            existing=existing,
            product=product,
            store=store,
            quantity=quantity,
            transaction_type=InventoryTransactionType.CUSTOMER_RETURN,
        )
        return existing


@transaction.atomic
def record_supplier_return(
    *,
    product,
    store,
    quantity,
    actor,
    reason,
    notes="",
    reference="",
    unit_cost=None,
    manufacturing_date=None,
    expiry_date=None,
    ip_address=None,
    request=None,
):
    return apply_stock_movement(
        product=product,
        store=store,
        transaction_type=InventoryTransactionType.SUPPLIER_RETURN,
        quantity=quantity,
        actor=actor,
        reason=reason,
        notes=notes,
        reference=reference,
        unit_cost=unit_cost,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        ip_address=ip_address,
        request=request,
    )


def _normalize_purchase_lines(lines):
    if not lines:
        raise ValidationError({"lines": "At least one purchase line is required."})
    normalized = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValidationError(
                {"lines": f"Line {index + 1} must be a mapping of line fields."}
            )
        product = line.get("product")
        if product is None:
            raise ValidationError({"lines": f"Line {index + 1} requires a product."})
        quantity = _validate_positive_quantity(line.get("quantity"))
        unit_cost = quantize_money(line.get("unit_cost", Decimal("0.00")))
        if unit_cost < 0:
            raise ValidationError(
                {"lines": f"Line {index + 1} unit cost cannot be negative."}
            )
        manufacturing_date = line.get("manufacturing_date")
        expiry_date = line.get("expiry_date")
        validate_manufacturing_and_expiry_dates(manufacturing_date, expiry_date)
        normalized.append(
            {
                "product": product,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "line_total": quantize_money(quantity * unit_cost),
                "manufacturing_date": manufacturing_date,
                "expiry_date": expiry_date,
                "notes": line.get("notes", "") or "",
            }
        )
    return normalized


@transaction.atomic
def create_purchase_entry(
    *,
    store,
    supplier_name,
    entry_date,
    lines,
    created_by,
    supplier_invoice_number="",
    notes="",
):
    """Create a DRAFT purchase entry with lines. Does not change stock."""
    normalized_lines = _normalize_purchase_lines(lines)
    for line in normalized_lines:
        _validate_store_product(store=store, product=line["product"])

    entry = PurchaseEntry(
        store=store,
        supplier_name=supplier_name,
        supplier_invoice_number=supplier_invoice_number or "",
        entry_date=entry_date,
        status=PurchaseEntryStatus.DRAFT,
        notes=notes or "",
        created_by=created_by,
        total_cost=Decimal("0.00"),
    )
    entry.full_clean()
    entry.save()

    for line in normalized_lines:
        entry_line = PurchaseEntryLine(
            purchase_entry=entry,
            product=line["product"],
            quantity=line["quantity"],
            unit_cost=line["unit_cost"],
            line_total=line["line_total"],
            manufacturing_date=line["manufacturing_date"],
            expiry_date=line["expiry_date"],
            notes=line["notes"],
        )
        entry_line.full_clean()
        entry_line.save()

    entry.recalculate_total_cost(save=True)
    entry.refresh_from_db()
    return entry


@transaction.atomic
def confirm_purchase_entry(
    *,
    purchase_entry,
    confirmed_by,
    ip_address=None,
    request=None,
):
    """
    Confirm a DRAFT purchase entry.

    For each line: create exactly one PURCHASE InventoryTransaction and increase
    Product.stock_quantity. total_cost is recalculated on the backend.
    """
    entry = PurchaseEntry.objects.select_for_update().get(pk=purchase_entry.pk)
    if entry.status != PurchaseEntryStatus.DRAFT:
        raise ValidationError(
            {"status": "Only draft purchase entries can be confirmed."}
        )

    lines = list(entry.lines.select_related("product").order_by("id"))
    if not lines:
        raise ValidationError({"lines": "Cannot confirm a purchase with no lines."})

    transactions = []
    for line in lines:
        _validate_store_product(store=entry.store, product=line.product)
        txn = apply_stock_movement(
            product=line.product,
            store=entry.store,
            transaction_type=InventoryTransactionType.PURCHASE,
            quantity=line.quantity,
            actor=confirmed_by,
            reason="Purchase stock-in",
            notes=line.notes,
            reference=entry.supplier_invoice_number or entry.entry_number,
            unit_cost=line.unit_cost,
            manufacturing_date=line.manufacturing_date,
            expiry_date=line.expiry_date,
            purchase_entry=entry,
            purchase_entry_line=line,
            ip_address=ip_address,
            request=request,
        )
        transactions.append(txn)

    entry.recalculate_total_cost(save=True)
    entry.status = PurchaseEntryStatus.CONFIRMED
    entry.confirmed_by = confirmed_by
    entry.confirmed_at = timezone.now()
    entry.save(
        update_fields=[
            "status",
            "confirmed_by",
            "confirmed_at",
            "total_cost",
            "updated_at",
        ]
    )
    return entry, transactions


@transaction.atomic
def record_purchase_stock_in(
    *,
    store,
    supplier_name,
    entry_date,
    lines,
    actor,
    supplier_invoice_number="",
    notes="",
    ip_address=None,
    request=None,
):
    """
    Create a confirmed purchase as one atomic service operation.

    In a single DB transaction this will:
      1. Validate every product belongs to ``store``
      2. Create PurchaseEntry + PurchaseEntryLine rows
      3. Create exactly one PURCHASE InventoryTransaction per line
      4. Increase each Product.stock_quantity exactly once (via the ledger)

    ``total_cost`` and each ``line_total`` are calculated on the backend from
    quantity × unit_cost. Unit cost is stored on both the line and the
    InventoryTransaction for future profit / cost reports.

    If any step fails, the atomic block rolls back entry, lines, ledger rows,
    and stock changes together.

    Returns (purchase_entry, list[InventoryTransaction]).
    """
    normalized_lines = _normalize_purchase_lines(lines)
    for line in normalized_lines:
        _validate_store_product(store=store, product=line["product"])

    total_cost = quantize_money(
        sum((line["line_total"] for line in normalized_lines), Decimal("0.00"))
    )
    now = timezone.now()
    entry = PurchaseEntry(
        store=store,
        supplier_name=supplier_name,
        supplier_invoice_number=supplier_invoice_number or "",
        entry_date=entry_date,
        status=PurchaseEntryStatus.CONFIRMED,
        notes=notes or "",
        created_by=actor,
        confirmed_by=actor,
        confirmed_at=now,
        total_cost=total_cost,
    )
    entry.full_clean()
    entry.save()

    transactions = []
    for line in normalized_lines:
        entry_line = PurchaseEntryLine(
            purchase_entry=entry,
            product=line["product"],
            quantity=line["quantity"],
            unit_cost=line["unit_cost"],
            line_total=line["line_total"],
            manufacturing_date=line["manufacturing_date"],
            expiry_date=line["expiry_date"],
            notes=line["notes"],
        )
        entry_line.full_clean()
        entry_line.save()

        txn = apply_stock_movement(
            product=line["product"],
            store=store,
            transaction_type=InventoryTransactionType.PURCHASE,
            quantity=line["quantity"],
            actor=actor,
            reason="Purchase stock-in",
            notes=line["notes"],
            reference=entry.supplier_invoice_number or entry.entry_number,
            unit_cost=line["unit_cost"],
            manufacturing_date=line["manufacturing_date"],
            expiry_date=line["expiry_date"],
            purchase_entry=entry,
            purchase_entry_line=entry_line,
            ip_address=ip_address,
            request=request,
        )
        transactions.append(txn)

    entry.recalculate_total_cost(save=True)
    entry.refresh_from_db()
    return entry, transactions


@transaction.atomic
def cancel_purchase_entry(*, purchase_entry, cancelled_by=None):
    """Cancel a DRAFT purchase entry. Confirmed entries cannot be cancelled."""
    entry = PurchaseEntry.objects.select_for_update().get(pk=purchase_entry.pk)
    if entry.status != PurchaseEntryStatus.DRAFT:
        raise ValidationError(
            {"status": "Only draft purchase entries can be cancelled."}
        )
    entry.status = PurchaseEntryStatus.CANCELLED
    entry.save(update_fields=["status", "updated_at"])
    return entry
