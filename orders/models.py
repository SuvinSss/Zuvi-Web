from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import IntegrityError, models, transaction

from catalog.models import ProductUnit

ORDER_DELETE_MESSAGE = (
    "Orders cannot be deleted. Cancel the order to preserve history."
)
STORE_ORDER_DELETE_MESSAGE = (
    "Store orders cannot be deleted. Update status or cancel instead."
)
ORDER_ITEM_DELETE_MESSAGE = (
    "Order items cannot be deleted. Order history must be preserved."
)

# Fields safe to expose on public/customer-facing surfaces.
# Never include store_price, profit margin, commission, or inventory internals.
ORDER_ITEM_PUBLIC_SNAPSHOT_FIELDS = (
    "product_name",
    "product_code",
    "sku",
    "unit",
    "unit_value",
    "unit_price",
    "quantity",
    "line_total",
)


class FulfillmentType(models.TextChoices):
    DELIVERY = "DELIVERY", "Delivery"
    FACILITY_PICKUP = "FACILITY_PICKUP", "Facility Pickup"


class PaymentMethod(models.TextChoices):
    COD = "COD", "Cash on Delivery"
    PAY_AT_PICKUP = "PAY_AT_PICKUP", "Pay at Pickup"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    COLLECTED = "COLLECTED", "Collected"
    CANCELLED = "CANCELLED", "Cancelled"


class OrderStatus(models.TextChoices):
    PLACED = "PLACED", "Placed"
    CONFIRMED = "CONFIRMED", "Confirmed"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"
    PARTIALLY_CANCELLED = "PARTIALLY_CANCELLED", "Partially Cancelled"
    CANCELLED = "CANCELLED", "Cancelled"


class StoreOrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    PREPARING = "PREPARING", "Preparing"
    READY = "READY", "Ready"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for Delivery"
    READY_FOR_PICKUP = "READY_FOR_PICKUP", "Ready for Pickup"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    REJECTED = "REJECTED", "Rejected"


class OrderQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError(ORDER_DELETE_MESSAGE)


class OrderManager(models.Manager.from_queryset(OrderQuerySet)):
    pass


class StoreOrderQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError(STORE_ORDER_DELETE_MESSAGE)


class StoreOrderManager(models.Manager.from_queryset(StoreOrderQuerySet)):
    pass


class OrderItemQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError(ORDER_ITEM_DELETE_MESSAGE)


class OrderItemManager(models.Manager.from_queryset(OrderItemQuerySet)):
    pass


class PickupLocation(models.Model):
    """
    Facility / counter where a customer may collect a StoreOrder.

    Belongs to one Store. Orders snapshot contact details separately when needed;
    this row remains the live catalogue of pickup points.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="pickup_locations",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=32, blank=True)
    address = models.ForeignKey(
        "locations.Address",
        on_delete=models.PROTECT,
        related_name="pickup_locations",
    )
    contact_phone = models.CharField(max_length=20, blank=True)
    hours = models.CharField(
        max_length=255,
        blank=True,
        help_text="Customer-facing pickup hours, e.g. Mon–Sat 9:00–20:00.",
    )
    instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["store__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "code"],
                condition=~models.Q(code=""),
                name="unique_pickup_location_code_per_store",
            ),
        ]

    def __str__(self):
        store_code = self.store.store_code if self.store_id else "—"
        return f"{self.name} @ {store_code}"


class Order(models.Model):
    """
    Customer-facing multi-store order parent.

    Products are never attached directly — use StoreOrder → OrderItem.
    Orders are not deleted through normal workflows; cancel instead.
    """

    order_number = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        blank=True,
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.PLACED,
    )
    fulfillment_type = models.CharField(
        max_length=32,
        choices=FulfillmentType.choices,
    )
    payment_method = models.CharField(
        max_length=32,
        choices=PaymentMethod.choices,
        default=PaymentMethod.COD,
    )
    payment_status = models.CharField(
        max_length=32,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    checkout_token = models.CharField(
        max_length=64,
        unique=True,
        help_text="Idempotency key supplied at checkout to prevent duplicate orders.",
    )
    # Optional link to the address book entry used at checkout (may later be deactivated).
    delivery_address = models.ForeignKey(
        "customers.CustomerAddress",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    # Delivery snapshot — frozen at checkout; do not rely on live CustomerAddress.
    delivery_recipient_name = models.CharField(max_length=150, blank=True)
    delivery_phone_number = models.CharField(max_length=20, blank=True)
    delivery_line1 = models.CharField(max_length=255, blank=True)
    delivery_line2 = models.CharField(max_length=255, blank=True)
    delivery_landmark = models.CharField(max_length=255, blank=True)
    delivery_city = models.CharField(max_length=100, blank=True)
    delivery_district = models.CharField(max_length=100, blank=True)
    delivery_state = models.CharField(max_length=100, blank=True)
    delivery_postal_code = models.CharField(max_length=20, blank=True)
    delivery_country = models.CharField(max_length=100, blank=True)
    delivery_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    delivery_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    delivery_instructions = models.TextField(blank=True)
    items_subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    delivery_charge = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    discount_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    grand_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    customer_notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_orders",
    )
    placed_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrderManager()

    class Meta:
        ordering = ["-placed_at", "-created_at"]
        permissions = (
            ("manage_order_status", "Can manage order status"),
            ("manage_payment_status", "Can manage order payment status"),
            ("view_all_orders", "Can view orders across all customers and stores"),
            ("cancel_order", "Can cancel orders administratively"),
        )
        indexes = [
            models.Index(fields=["customer", "-placed_at"]),
            models.Index(fields=["status", "-placed_at"]),
            models.Index(fields=["payment_status", "-placed_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(items_subtotal__gte=Decimal("0")),
                name="order_items_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(delivery_charge__gte=Decimal("0")),
                name="order_delivery_charge_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_total__gte=Decimal("0")),
                name="order_discount_total_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(grand_total__gte=Decimal("0")),
                name="order_grand_total_non_negative",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.fulfillment_type == FulfillmentType.DELIVERY:
            if not (self.delivery_line1 or "").strip():
                errors["delivery_line1"] = (
                    "Delivery address line 1 is required for delivery orders."
                )
            if not (self.delivery_city or "").strip():
                errors["delivery_city"] = (
                    "Delivery city is required for delivery orders."
                )
            if not (self.delivery_recipient_name or "").strip():
                errors["delivery_recipient_name"] = (
                    "Recipient name is required for delivery orders."
                )
            if not (self.delivery_phone_number or "").strip():
                errors["delivery_phone_number"] = (
                    "Phone number is required for delivery orders."
                )
        for field in (
            "items_subtotal",
            "delivery_charge",
            "discount_total",
            "grand_total",
        ):
            value = getattr(self, field, None)
            if value is not None and value < 0:
                errors[field] = "Amount cannot be negative."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.order_number:
            return super().save(*args, **kwargs)

        from .services import ORDER_NUMBER_MAX_ATTEMPTS, generate_order_number

        last_error = None
        for _ in range(ORDER_NUMBER_MAX_ATTEMPTS):
            self.order_number = generate_order_number(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.order_number = ""
                if self.pk:
                    raise
        raise IntegrityError(
            "Could not allocate a unique order number under concurrent load."
        ) from last_error

    def delete(self, *args, **kwargs):
        raise ValidationError(ORDER_DELETE_MESSAGE)

    def __str__(self):
        return self.order_number or f"Order#{self.pk or 'new'}"


class StoreOrder(models.Model):
    """Per-store slice of a multi-store customer Order."""

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="store_orders",
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.PROTECT,
        related_name="store_orders",
    )
    store_order_number = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=StoreOrderStatus.choices,
        default=StoreOrderStatus.PENDING,
    )
    pickup_location = models.ForeignKey(
        PickupLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="store_orders",
    )
    # Snapshot of store identity at checkout.
    store_name = models.CharField(max_length=200)
    store_code = models.CharField(max_length=32)
    items_subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    delivery_charge = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    store_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StoreOrderManager()

    class Meta:
        ordering = ["order_id", "id"]
        indexes = [
            models.Index(fields=["store", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "store"],
                name="unique_store_order_per_order_store",
            ),
            models.CheckConstraint(
                condition=models.Q(items_subtotal__gte=Decimal("0")),
                name="store_order_items_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(delivery_charge__gte=Decimal("0")),
                name="store_order_delivery_charge_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(store_total__gte=Decimal("0")),
                name="store_order_total_non_negative",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.order_id and self.pickup_location_id:
            if self.order.fulfillment_type != FulfillmentType.FACILITY_PICKUP:
                errors["pickup_location"] = (
                    "Pickup location is only valid for facility-pickup orders."
                )
        if self.pickup_location_id and self.store_id:
            if self.pickup_location.store_id != self.store_id:
                errors["pickup_location"] = (
                    "Pickup location must belong to the same store as this store order."
                )
        if (
            self.order_id
            and self.order.fulfillment_type == FulfillmentType.FACILITY_PICKUP
            and not self.pickup_location_id
        ):
            errors["pickup_location"] = (
                "Pickup location is required for facility-pickup store orders."
            )
        for field in ("items_subtotal", "delivery_charge", "store_total"):
            value = getattr(self, field, None)
            if value is not None and value < 0:
                errors[field] = "Amount cannot be negative."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.store_order_number:
            return super().save(*args, **kwargs)

        from .services import (
            STORE_ORDER_NUMBER_MAX_ATTEMPTS,
            generate_store_order_number,
        )

        last_error = None
        for _ in range(STORE_ORDER_NUMBER_MAX_ATTEMPTS):
            self.store_order_number = generate_store_order_number(exclude_pk=self.pk)
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                last_error = exc
                self.store_order_number = ""
                if self.pk:
                    raise
        raise IntegrityError(
            "Could not allocate a unique store order number under concurrent load."
        ) from last_error

    def delete(self, *args, **kwargs):
        raise ValidationError(STORE_ORDER_DELETE_MESSAGE)

    def __str__(self):
        return self.store_order_number or f"StoreOrder#{self.pk or 'new'}"


class OrderItem(models.Model):
    """
    Line item with historical product snapshots.

    unit_price is the customer-facing final price at checkout.
    Internal catalogue fields (store_price, margins) are intentionally omitted.
    """

    store_order = models.ForeignKey(
        StoreOrder,
        on_delete=models.PROTECT,
        related_name="items",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=200)
    product_code = models.CharField(max_length=32)
    sku = models.CharField(max_length=64)
    unit = models.CharField(max_length=16, choices=ProductUnit.choices)
    unit_value = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Customer-facing unit price (Product.final_price) at checkout.",
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    # Once-only inventory restoration guard for cancel / reject flows.
    stock_restored = models.BooleanField(
        default=False,
        help_text=(
            "True after checkout stock for this line has been restored. "
            "Prevents a second restoration on repeated cancel/reject."
        ),
    )
    stock_restored_at = models.DateTimeField(null=True, blank=True)
    # Cancellation marker — rows are never deleted.
    is_cancelled = models.BooleanField(
        default=False,
        help_text="True after the parent order/store-order cancellation marked this line cancelled.",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Rejection marker — set when the owning StoreOrder is rejected.
    is_rejected = models.BooleanField(
        default=False,
        help_text="True after the owning StoreOrder rejection marked this line rejected.",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrderItemManager()

    class Meta:
        ordering = ["store_order_id", "id"]
        indexes = [
            models.Index(fields=["product"]),
            models.Index(fields=["product_code"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=Decimal("0")),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=Decimal("0")),
                name="order_item_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=Decimal("0")),
                name="order_item_line_total_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_value__gte=Decimal("0")),
                name="order_item_unit_value_non_negative",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."
        if self.unit_price is not None and self.unit_price < 0:
            errors["unit_price"] = "Unit price cannot be negative."
        if self.line_total is not None and self.line_total < 0:
            errors["line_total"] = "Line total cannot be negative."
        if self.product_id and self.store_order_id:
            if self.product.store_id != self.store_order.store_id:
                errors["product"] = (
                    "Product must belong to the same store as the store order."
                )
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        raise ValidationError(ORDER_ITEM_DELETE_MESSAGE)

    def public_snapshot(self):
        """Return customer-safe snapshot fields only."""
        return {field: getattr(self, field) for field in ORDER_ITEM_PUBLIC_SNAPSHOT_FIELDS}

    def __str__(self):
        return f"{self.product_code} × {self.quantity}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=32,
        choices=OrderStatus.choices,
        blank=True,
    )
    new_status = models.CharField(max_length=32, choices=OrderStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_status_changes",
    )
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "order status histories"
        ordering = ["-created_at"]

    def __str__(self):
        old = self.old_status or "—"
        number = self.order.order_number if self.order_id else "—"
        return f"{number}: {old} → {self.new_status}"


class StoreOrderStatusHistory(models.Model):
    store_order = models.ForeignKey(
        StoreOrder,
        on_delete=models.PROTECT,
        related_name="status_history",
    )
    old_status = models.CharField(
        max_length=32,
        choices=StoreOrderStatus.choices,
        blank=True,
    )
    new_status = models.CharField(max_length=32, choices=StoreOrderStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="store_order_status_changes",
    )
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "store order status histories"
        ordering = ["-created_at"]

    def __str__(self):
        old = self.old_status or "—"
        number = (
            self.store_order.store_order_number if self.store_order_id else "—"
        )
        return f"{number}: {old} → {self.new_status}"
