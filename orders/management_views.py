"""Management-portal Order list, detail, status and StoreOrder views."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET

from customers.models import Customer
from stores.models import Store

from .decorators import order_permission_required, user_has_order_permission
from .forms import (
    ManagementOrderCancelForm,
    ManagementOrderStatusForm,
    ManagementPaymentStatusForm,
)
from .management import (
    apply_management_order_filters,
    get_management_order_or_404,
    get_management_store_order_or_404,
    inventory_transactions_for_order_items,
    management_orders_queryset,
)
from .management_status import (
    admin_can_cancel_order,
    admin_cancel_order,
    available_admin_order_statuses,
    available_admin_payment_statuses,
    update_order_payment_status,
    update_order_status,
)
from .models import (
    FulfillmentType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)


def _validation_message(exc):
    if hasattr(exc, "message_dict"):
        first = next(iter(exc.message_dict.values()))
        return first[0] if isinstance(first, list) else first
    return "; ".join(exc.messages)


def _management_list_query_string(request, *, page=None):
    params = request.GET.copy()
    if page is None:
        params.pop("page", None)
    else:
        params["page"] = page
    return params.urlencode()


def _order_detail_redirect(order_number):
    return redirect(
        "orders:management_order_detail",
        order_number=order_number,
    )


def _collect_order_items(order):
    items = []
    for store_order in order.store_orders.all():
        items.extend(list(store_order.items.all()))
    return items


@never_cache
@require_GET
@order_permission_required("orders.view_order")
def management_order_list_view(request):
    queryset = management_orders_queryset()
    queryset, filters = apply_management_order_filters(queryset, request.GET)
    page_obj = Paginator(queryset, 25).get_page(request.GET.get("page"))

    return render(
        request,
        "management/orders/list.html",
        {
            "page_obj": page_obj,
            "query_string": _management_list_query_string(request),
            "status_choices": OrderStatus.choices,
            "fulfillment_choices": FulfillmentType.choices,
            "payment_method_choices": PaymentMethod.choices,
            "payment_status_choices": PaymentStatus.choices,
            "stores": Store.objects.order_by("name"),
            "customers": Customer.objects.select_related("user").order_by(
                "user__first_name",
                "user__last_name",
                "customer_code",
            )[:500],
            "can_change_order": user_has_order_permission(
                request.user, "orders.change_order"
            ),
            "can_cancel_order": user_has_order_permission(
                request.user, "orders.cancel_order"
            ),
            **filters,
        },
    )


@never_cache
@require_GET
@order_permission_required("orders.view_order")
def management_order_detail_view(request, order_number):
    order = get_management_order_or_404(order_number)
    store_orders = list(order.store_orders.all())
    order_items = _collect_order_items(order)
    inventory_rows = inventory_transactions_for_order_items(order_items)

    allowed_statuses = available_admin_order_statuses(order)
    allowed_payment = available_admin_payment_statuses(order)
    can_change = user_has_order_permission(request.user, "orders.change_order")
    can_cancel = user_has_order_permission(request.user, "orders.cancel_order")
    can_manage_payment = user_has_order_permission(
        request.user, "orders.manage_payment_status"
    )

    return render(
        request,
        "management/orders/detail.html",
        {
            "order": order,
            "store_orders": store_orders,
            "order_items": order_items,
            "status_history": order.status_history.all(),
            "inventory_rows": inventory_rows,
            "can_change_order": can_change,
            "can_cancel_order": can_cancel and admin_can_cancel_order(order),
            "can_manage_payment": can_manage_payment and bool(allowed_payment),
            "status_form": ManagementOrderStatusForm(
                allowed_statuses=allowed_statuses,
                prefix="status",
            )
            if can_change and allowed_statuses
            else None,
            "cancel_form": ManagementOrderCancelForm(prefix="cancel")
            if can_cancel and admin_can_cancel_order(order)
            else None,
            "payment_form": ManagementPaymentStatusForm(
                allowed_statuses=allowed_payment,
                prefix="payment",
            )
            if can_manage_payment and allowed_payment
            else None,
        },
    )


@csrf_protect
@never_cache
@order_permission_required("orders.view_order")
def management_order_change_status_view(request, order_number):
    """
    POST-only status / cancel / payment mutations.

    Permission is re-checked per action:
    - update_status → orders.change_order
    - cancel → orders.cancel_order
    - update_payment → orders.manage_payment_status
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    order = get_management_order_or_404(order_number)
    action = (request.POST.get("action") or "").strip().lower()

    try:
        if action == "update_status":
            if not user_has_order_permission(request.user, "orders.change_order"):
                raise PermissionDenied(
                    "You do not have permission to change order status."
                )
            form = ManagementOrderStatusForm(
                request.POST,
                allowed_statuses=available_admin_order_statuses(order),
                prefix="status",
            )
            if not form.is_valid():
                for errors in form.errors.values():
                    for error in errors:
                        messages.error(request, error)
                return _order_detail_redirect(order.order_number)
            update_order_status(
                order=order,
                new_status=form.cleaned_data["status"],
                actor=request.user,
                reason=form.cleaned_data.get("reason") or "",
                request=request,
            )
            messages.success(
                request,
                f"Order {order.order_number} status updated to "
                f"{form.cleaned_data['status']}.",
            )

        elif action == "cancel":
            if not user_has_order_permission(request.user, "orders.cancel_order"):
                raise PermissionDenied(
                    "You do not have permission to cancel orders."
                )
            form = ManagementOrderCancelForm(request.POST, prefix="cancel")
            if not form.is_valid():
                for error in form.errors.get("reason", form.errors.get("__all__", [])):
                    messages.error(request, error)
                return _order_detail_redirect(order.order_number)
            admin_cancel_order(
                order=order,
                actor=request.user,
                reason=form.cleaned_data["reason"],
                request=request,
            )
            messages.success(
                request,
                f"Order {order.order_number} has been cancelled.",
            )

        elif action == "update_payment":
            if not user_has_order_permission(
                request.user, "orders.manage_payment_status"
            ):
                raise PermissionDenied(
                    "You do not have permission to manage payment status."
                )
            form = ManagementPaymentStatusForm(
                request.POST,
                allowed_statuses=available_admin_payment_statuses(order),
                prefix="payment",
            )
            if not form.is_valid():
                for errors in form.errors.values():
                    for error in errors:
                        messages.error(request, error)
                return _order_detail_redirect(order.order_number)
            update_order_payment_status(
                order=order,
                new_payment_status=form.cleaned_data["payment_status"],
                actor=request.user,
                reason=form.cleaned_data.get("reason") or "",
                request=request,
            )
            messages.success(
                request,
                f"Order {order.order_number} payment status updated to "
                f"{form.cleaned_data['payment_status']}.",
            )

        else:
            messages.error(request, "Unknown order action.")

    except PermissionDenied:
        raise
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))

    return _order_detail_redirect(order.order_number)


@never_cache
@require_GET
@order_permission_required("orders.view_order")
def management_store_order_detail_view(request, store_order_number):
    store_order = get_management_store_order_or_404(store_order_number)
    items = list(store_order.items.all())
    inventory_rows = inventory_transactions_for_order_items(items)
    return render(
        request,
        "management/orders/store_order_detail.html",
        {
            "store_order": store_order,
            "order": store_order.order,
            "items": items,
            "status_history": store_order.status_history.all(),
            "order_status_history": store_order.order.status_history.all(),
            "inventory_rows": inventory_rows,
            "can_change_order": user_has_order_permission(
                request.user, "orders.change_order"
            ),
            "can_cancel_order": user_has_order_permission(
                request.user, "orders.cancel_order"
            ),
        },
    )
