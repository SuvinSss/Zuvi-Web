from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from catalog.pricing import quantize_money


class InventoryDirection(models.TextChoices):
    IN = "IN", "In"
    OUT = "OUT", "Out"


class InventoryTransactionType(models.TextChoices):
    OPENING = "OPENING", "Opening Stock"
    PURCHASE = "PURCHASE", "Purchase Stock-In"
    STOCK_IN = "STOCK_IN", "Manual Stock-In"
    STOCK_OUT = "STOCK_OUT", "Manual Stock-Out"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment In"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment Out"
    DAMAGED = "DAMAGED", "Damaged"
    EXPIRED = "EXPIRED", "Expired"
    CUSTOMER_RETURN = "CUSTOMER_RETURN", "Customer Return"
    SUPPLIER_RETURN = "SUPPLIER_RETURN", "Supplier Return"


class PurchaseEntryStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"


TRANSACTION_TYPE_DIRECTION = {
    InventoryTransactionType.OPENING: InventoryDirection.IN,
    InventoryTransactionType.PURCHASE: InventoryDirection.IN,
    InventoryTransactionType.STOCK_IN: InventoryDirection.IN,
    InventoryTransactionType.STOCK_OUT: InventoryDirection.OUT,
    InventoryTransactionType.ADJUSTMENT_IN: InventoryDirection.IN,
    InventoryTransactionType.ADJUSTMENT_OUT: InventoryDirection.OUT,
    InventoryTransactionType.DAMAGED: InventoryDirection.OUT,
    InventoryTransactionType.EXPIRED: InventoryDirection.OUT,
    InventoryTransactionType.CUSTOMER_RETURN: InventoryDirection.IN,
    InventoryTransactionType.SUPPLIER_RETURN: InventoryDirection.OUT,
}

REASON_REQUIRED_TYPES = frozenset(
    {
        InventoryTransactionType.STOCK_OUT,
        InventoryTransactionType.ADJUSTMENT_IN,
        InventoryTransactionType.ADJUSTMENT_OUT,
        InventoryTransactionType.DAMAGED,
        InventoryTransactionType.EXPIRED,
        InventoryTransactionType.SUPPLIER_RETURN,
    }
)

IMMUTABLE_TRANSACTION_UPDATE_MESSAGE = (
    "Inventory transactions are immutable and cannot be updated. "
    "Record a reversing or adjustment transaction instead."
)
IMMUTABLE_TRANSACTION_DELETE_MESSAGE = (
    "Inventory transactions are immutable and cannot be deleted. "
    "Record a reversing or adjustment transaction instead."
)


def validate_manufacturing_and_expiry_dates(manufacturing_date, expiry_date):
    """Shared manufacturing / expiry validation for inventory records."""
    errors = {}
    today = timezone.localdate()
    if manufacturing_date and manufacturing_date > today:
        errors["manufacturing_date"] = "Manufacturing date cannot be in the future."
    if (
        manufacturing_date
        and expiry_date
        and expiry_date < manufacturing_date
    ):
        errors["expiry_date"] = (
            "Expiry date must be on or after the manufacturing date."
        )
    if errors:
        raise ValidationError(errors)


class InventoryTransactionQuerySet(models.QuerySet):
    """Block bulk paths that would silently rewrite or remove ledger history."""

    def update(self, **kwargs):
        raise ValidationError(IMMUTABLE_TRANSACTION_UPDATE_MESSAGE)

    def delete(self):
        raise ValidationError(IMMUTABLE_TRANSACTION_DELETE_MESSAGE)

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError(IMMUTABLE_TRANSACTION_UPDATE_MESSAGE)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False,
                    update_fields=None, unique_fields=None):
        raise ValidationError(
            "Inventory transactions must be created through the inventory "
            "service one row at a time."
        )


class InventoryTransactionManager(models.Manager.from_queryset(InventoryTransactionQuerySet)):
    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError(IMMUTABLE_TRANSACTION_UPDATE_MESSAGE)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError(
            "Inventory transactions must be created through the inventory "
            "service one row at a time."
        )


class PurchaseEntry(models.Model):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="purchase_entries",
    )
    entry_number = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        blank=True,
    )
    supplier_name = models.CharField(max_length=200)
    supplier_invoice_number = models.CharField(max_length=100, blank=True)
    entry_date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=PurchaseEntryStatus.choices,
        default=PurchaseEntryStatus.DRAFT,
    )
    total_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_purchase_entries",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confirmed_purchase_entries",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "-created_at"]),
            models.Index(fields=["store", "status"]),
            models.Index(fields=["entry_date"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_cost__gte=Decimal("0")),
                name="purchase_entry_total_cost_non_negative",
            ),
        ]

    def recalculate_total_cost(self, *, save=True):
        total = Decimal("0.00")
        for line in self.lines.all():
            total += line.line_total
        self.total_cost = quantize_money(total)
        if save and self.pk:
            type(self).objects.filter(pk=self.pk).update(
                total_cost=self.total_cost,
                updated_at=timezone.now(),
            )
        return self.total_cost

    def clean(self):
        super().clean()
        if self.entry_date and self.entry_date > timezone.localdate():
            raise ValidationError(
                {"entry_date": "Purchase entry date cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        if self.entry_number:
            return super().save(*args, **kwargs)

        from .services import ENTRY_NUMBER_MAX_ATTEMPTS, generate_purchase_entry_number

        last_error = None
        for _ in range(ENTRY_NUMBER_MAX_ATTEMPTS):
            self.entry_number = generate_purchase_entry_number(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.entry_number = ""
                if self.pk:
                    raise
        raise IntegrityError(
            "Could not allocate a unique purchase entry number under concurrent load."
        ) from last_error

    def __str__(self):
        return f"{self.entry_number} ({self.store_id})"


class PurchaseEntryLine(models.Model):
    purchase_entry = models.ForeignKey(
        PurchaseEntry,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="purchase_entry_lines",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        editable=False,
        validators=[MinValueValidator(Decimal("0"))],
    )
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["purchase_entry", "product"]),
            models.Index(fields=["product"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=Decimal("0")),
                name="purchase_entry_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=Decimal("0")),
                name="purchase_entry_line_unit_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=Decimal("0")),
                name="purchase_entry_line_total_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manufacturing_date__isnull=True)
                    | models.Q(expiry_date__isnull=True)
                    | models.Q(expiry_date__gte=models.F("manufacturing_date"))
                ),
                name="purchase_line_expiry_on_or_after_manufacturing",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."
        if self.unit_cost is not None and self.unit_cost < 0:
            errors["unit_cost"] = "Unit cost cannot be negative."
        if self.product_id and self.purchase_entry_id:
            if self.product.store_id != self.purchase_entry.store_id:
                errors["product"] = (
                    "Product must belong to the same store as the purchase entry."
                )
        try:
            validate_manufacturing_and_expiry_dates(
                self.manufacturing_date,
                self.expiry_date,
            )
        except ValidationError as exc:
            if hasattr(exc, "error_dict"):
                errors.update(exc.error_dict)
            else:
                errors.setdefault("__all__", []).extend(exc.messages)
        if errors:
            raise ValidationError(errors)
        if self.quantity is not None and self.unit_cost is not None:
            self.line_total = quantize_money(self.quantity * self.unit_cost)

    def save(self, *args, **kwargs):
        if self.quantity is not None and self.unit_cost is not None:
            self.line_total = quantize_money(self.quantity * self.unit_cost)
        super().save(*args, **kwargs)
        if self.purchase_entry_id:
            self.purchase_entry.recalculate_total_cost(save=True)

    def __str__(self):
        return f"{self.purchase_entry.entry_number} / {self.product_id}"


class InventoryTransaction(models.Model):
    """
    Append-only stock ledger row.

    Existing rows must never be edited or deleted through normal model/admin
    paths. Corrections create a new reversing or adjustment transaction.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="inventory_transactions",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="inventory_transactions",
    )
    transaction_number = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        blank=True,
    )
    transaction_type = models.CharField(
        max_length=32,
        choices=InventoryTransactionType.choices,
    )
    direction = models.CharField(
        max_length=8,
        choices=InventoryDirection.choices,
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    previous_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0"))],
    )
    new_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    reference = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    purchase_entry = models.ForeignKey(
        PurchaseEntry,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    purchase_entry_line = models.ForeignKey(
        PurchaseEntryLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_system_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = InventoryTransactionManager()

    class Meta:
        ordering = ["-created_at"]
        permissions = (
            ("view_all_inventory", "Can view inventory across all stores"),
            ("record_purchase", "Can record purchase stock-in entries"),
            ("adjust_inventory", "Can record manual inventory adjustments"),
            ("record_damage", "Can record damaged stock"),
            ("record_expiry", "Can record expired stock"),
            ("export_inventory", "Can export inventory data"),
        )
        indexes = [
            models.Index(fields=["store", "-created_at"]),
            models.Index(fields=["product", "-created_at"]),
            models.Index(fields=["store", "transaction_type"]),
            models.Index(fields=["transaction_type", "-created_at"]),
            models.Index(fields=["purchase_entry"]),
            models.Index(fields=["reference"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=Decimal("0")),
                name="inventory_transaction_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(previous_quantity__gte=Decimal("0")),
                name="inventory_transaction_previous_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(new_quantity__gte=Decimal("0")),
                name="inventory_transaction_new_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(unit_cost__isnull=True)
                    | models.Q(unit_cost__gte=Decimal("0"))
                ),
                name="inventory_transaction_unit_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manufacturing_date__isnull=True)
                    | models.Q(expiry_date__isnull=True)
                    | models.Q(expiry_date__gte=models.F("manufacturing_date"))
                ),
                name="inventory_txn_expiry_on_or_after_manufacturing",
            ),
            # Order deduct/restore keys (order-item:{id}:deduct|restore) are
            # immutable once-only ledger references.
            models.UniqueConstraint(
                fields=["reference"],
                condition=models.Q(reference__startswith="order-item:"),
                name="inventory_txn_unique_order_item_reference",
            ),
        ]

    def _assert_mutable_create_only(self, *, force_update=False):
        if force_update or not self._state.adding:
            raise ValidationError(IMMUTABLE_TRANSACTION_UPDATE_MESSAGE)
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(IMMUTABLE_TRANSACTION_UPDATE_MESSAGE)

    def clean(self):
        super().clean()
        errors = {}

        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."

        expected_direction = TRANSACTION_TYPE_DIRECTION.get(self.transaction_type)
        if expected_direction and self.direction and self.direction != expected_direction:
            errors["direction"] = (
                f"Direction for {self.transaction_type} must be {expected_direction}."
            )

        if (
            self.transaction_type in REASON_REQUIRED_TYPES
            and not (self.reason or "").strip()
        ):
            errors["reason"] = "A reason is required for this stock movement."

        if self.product_id and self.store_id:
            if self.product.store_id != self.store_id:
                errors["product"] = "Product must belong to the selected store."

        if self.purchase_entry_id and self.store_id:
            if self.purchase_entry.store_id != self.store_id:
                errors["purchase_entry"] = (
                    "Purchase entry must belong to the selected store."
                )

        try:
            validate_manufacturing_and_expiry_dates(
                self.manufacturing_date,
                self.expiry_date,
            )
        except ValidationError as exc:
            if hasattr(exc, "error_dict"):
                errors.update(exc.error_dict)
            else:
                errors.setdefault("__all__", []).extend(exc.messages)

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self._assert_mutable_create_only(
            force_update=bool(kwargs.get("force_update"))
        )

        if not self.direction and self.transaction_type:
            self.direction = TRANSACTION_TYPE_DIRECTION[self.transaction_type]

        if self.transaction_number:
            return super().save(*args, **kwargs)

        from .services import (
            TRANSACTION_NUMBER_MAX_ATTEMPTS,
            generate_transaction_number,
        )

        last_error = None
        for _ in range(TRANSACTION_NUMBER_MAX_ATTEMPTS):
            self.transaction_number = generate_transaction_number(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.transaction_number = ""
                if self.pk:
                    # Insert rolled back; clear in-memory pk so retries stay creates.
                    self.pk = None
                    self._state.adding = True
        raise IntegrityError(
            "Could not allocate a unique inventory transaction number "
            "under concurrent load."
        ) from last_error

    def delete(self, *args, **kwargs):
        raise ValidationError(IMMUTABLE_TRANSACTION_DELETE_MESSAGE)

    def __str__(self):
        return (
            f"{self.transaction_number}: {self.transaction_type} "
            f"{self.quantity} ({self.previous_quantity} → {self.new_quantity})"
        )
