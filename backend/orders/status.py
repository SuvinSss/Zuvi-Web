"""Order and StoreOrder status transition rules."""

from django.core.exceptions import ValidationError

from .models import OrderStatus, StoreOrderStatus

# Customer may cancel while the parent Order is still early-stage.
# Order.PLACED is the domain equivalent of a pending customer order.
CUSTOMER_CANCELLABLE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PLACED,
        OrderStatus.CONFIRMED,
    }
)

ADMIN_CANCELLABLE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PLACED,
        OrderStatus.CONFIRMED,
        OrderStatus.IN_PROGRESS,
        OrderStatus.PARTIALLY_CANCELLED,
    }
)

# Store may reject a StoreOrder only while it is still PENDING.
STORE_REJECTABLE_STATUSES = frozenset(
    {
        StoreOrderStatus.PENDING,
    }
)

# StoreOrders that no longer contribute to the customer-payable total.
STORE_ORDER_NON_CHARGEABLE_STATUSES = frozenset(
    {
        StoreOrderStatus.REJECTED,
        StoreOrderStatus.CANCELLED,
    }
)

# StoreOrders that still hold deducted stock and can be cancelled with the parent.
STORE_ORDER_ACTIVE_STATUSES = frozenset(
    {
        StoreOrderStatus.PENDING,
        StoreOrderStatus.ACCEPTED,
        StoreOrderStatus.PREPARING,
        StoreOrderStatus.READY,
        StoreOrderStatus.OUT_FOR_DELIVERY,
        StoreOrderStatus.READY_FOR_PICKUP,
    }
)

STORE_ORDER_TERMINAL_STATUSES = frozenset(
    {
        StoreOrderStatus.COMPLETED,
        StoreOrderStatus.CANCELLED,
        StoreOrderStatus.REJECTED,
    }
)

# Customer cancel is blocked once any StoreOrder has progressed into
# processing / ready / fulfilled states (PREPARING maps to "PROCESSING").
CUSTOMER_CANCEL_BLOCKING_STORE_STATUSES = frozenset(
    {
        StoreOrderStatus.PREPARING,
        StoreOrderStatus.READY,
        StoreOrderStatus.OUT_FOR_DELIVERY,
        StoreOrderStatus.READY_FOR_PICKUP,
        StoreOrderStatus.COMPLETED,
    }
)

# StoreOrders a customer cancel may still move to CANCELLED.
CUSTOMER_CANCELABLE_STORE_STATUSES = frozenset(
    {
        StoreOrderStatus.PENDING,
        StoreOrderStatus.ACCEPTED,
    }
)


def validate_customer_order_cancellation(*, order, store_orders=None):
    """
    Customer cancel rules.

    - Already CANCELLED: allowed (idempotent no-op path for the service).
    - Parent must be PLACED (pending) or CONFIRMED.
    - No StoreOrder may be PREPARING/READY/COMPLETED/fulfilled.
    """
    if order.status == OrderStatus.CANCELLED:
        return
    if order.status not in CUSTOMER_CANCELLABLE_ORDER_STATUSES:
        raise ValidationError(
            {
                "status": (
                    f"Order {order.order_number} cannot be cancelled from "
                    f"status {order.status}."
                )
            }
        )

    if store_orders is None:
        store_orders = order.store_orders.all()

    blockers = [
        so
        for so in store_orders
        if so.status in CUSTOMER_CANCEL_BLOCKING_STORE_STATUSES
    ]
    if blockers:
        sample = blockers[0]
        raise ValidationError(
            {
                "status": (
                    f"Order {order.order_number} cannot be cancelled because "
                    f"store order {sample.store_order_number} is "
                    f"{sample.status}."
                )
            }
        )


def validate_admin_order_cancellation(*, order):
    if order.status == OrderStatus.CANCELLED:
        return
    if order.status not in ADMIN_CANCELLABLE_ORDER_STATUSES:
        raise ValidationError(
            {
                "status": (
                    f"Order {order.order_number} cannot be cancelled from "
                    f"status {order.status}."
                )
            }
        )


def validate_store_order_rejection(*, store_order):
    if store_order.status == StoreOrderStatus.REJECTED:
        return
    if store_order.status not in STORE_REJECTABLE_STATUSES:
        raise ValidationError(
            {
                "status": (
                    f"Store order {store_order.store_order_number} cannot be "
                    f"rejected from status {store_order.status}."
                )
            }
        )
