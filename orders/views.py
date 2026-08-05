from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from customers.decorators import customer_portal_required
from stores.decorators import store_portal_required

from .cancellation import cancel_customer_order
from .checkout import place_customer_order
from .decorators import store_orders_manage_required, store_user_can_manage_orders
from .forms import (
    CheckoutPlaceForm,
    CustomerOrderCancelForm,
    StoreOrderRejectForm,
    StoreOrderStatusNoteForm,
)
from .models import FulfillmentType, PaymentMethod
from .portal import (
    customer_can_cancel_order,
    customer_orders_queryset,
    get_customer_order_or_404,
)
from .services import (
    build_checkout_preview,
    clear_checkout_token,
    issue_checkout_token,
    verify_checkout_token,
)
from .store_portal import (
    get_portal_store_order_or_404,
    portal_store_orders_queryset,
    store_order_action_context,
)
from .store_status import transition_store_order


def _validation_message(exc):
    if hasattr(exc, "message_dict"):
        first = next(iter(exc.message_dict.values()))
        return first[0] if isinstance(first, list) else first
    return "; ".join(exc.messages)


@never_cache
@require_GET
@customer_portal_required
def checkout_preview_view(request):
    """
    Checkout preview: recalculated prices, availability, and fulfillment options.

    Issues a fresh one-time checkout token bound to this customer session.
    """
    customer = request.customer
    preview = build_checkout_preview(customer)

    if not preview["delivery_addresses"]:
        messages.info(
            request, "Add a delivery address before you can check out."
        )
        return redirect(
            f"{reverse('customers:customer_portal_address_create')}"
            f"?next={quote(request.get_full_path())}"
        )

    checkout_token = issue_checkout_token(request, customer)

    form = CheckoutPlaceForm(
        initial={
            "checkout_token": checkout_token,
            "fulfillment_type": FulfillmentType.DELIVERY,
            "payment_method": PaymentMethod.COD,
        }
    )

    context = {
        **preview,
        "checkout_token": checkout_token,
        "form": form,
        "can_place_order": (
            not preview["is_empty"] and not preview["has_blocking_issues"]
        ),
    }
    return render(request, "orders/checkout.html", context)


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def checkout_place_view(request):
    """
    Place an order from the authenticated customer's cart.

    Accepts only fulfillment/payment selections, address/pickup IDs, notes and
    the server-issued checkout token. Never trusts prices or customer/store IDs.
    """
    customer = request.customer
    form = CheckoutPlaceForm(request.POST)
    if not form.is_valid():
        for _field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)
        return redirect("orders:checkout_preview")

    data = form.cleaned_data
    try:
        token = verify_checkout_token(
            request,
            customer,
            data["checkout_token"],
        )
        order = place_customer_order(
            customer=customer,
            checkout_token=token,
            fulfillment_type=data["fulfillment_type"],
            payment_method=data["payment_method"],
            delivery_address_id=data.get("delivery_address_id"),
            pickup_post_data=request.POST,
            customer_notes=data.get("customer_notes") or "",
            actor=request.user,
            request=request,
        )
        clear_checkout_token(request)
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect("orders:checkout_preview")

    messages.success(
        request,
        f"Order {order.order_number} placed successfully.",
    )
    return redirect("orders:customer_order_detail", order_number=order.order_number)


@never_cache
@require_GET
@customer_portal_required
def customer_order_list_view(request):
    """Authenticated customer's order history — scoped to request.customer only."""
    orders = customer_orders_queryset(request.customer)
    return render(
        request,
        "orders/customer_order_list.html",
        {"orders": orders},
    )


@never_cache
@require_GET
@customer_portal_required
def customer_order_detail_view(request, order_number):
    """
    Order detail for the authenticated customer.

    Another customer's order_number yields 404. Templates must only show
    public OrderItem snapshot fields (never store_price / margins).
    """
    order = get_customer_order_or_404(request.customer, order_number)
    cancel_form = CustomerOrderCancelForm()
    return render(
        request,
        "orders/customer_order_detail.html",
        {
            "order": order,
            "store_orders": order.store_orders.all(),
            "status_history": order.status_history.all(),
            "can_cancel": customer_can_cancel_order(order),
            "cancel_form": cancel_form,
        },
    )


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def customer_order_cancel_view(request, order_number):
    """
    Cancel an owned order. POST only.

    Ownership is enforced via get_customer_order_or_404 before the service call.
    """
    order = get_customer_order_or_404(request.customer, order_number)
    form = CustomerOrderCancelForm(request.POST)
    if not form.is_valid():
        for error in form.errors.get("reason", form.errors.get("__all__", [])):
            messages.error(request, error)
        return redirect(
            "orders:customer_order_detail",
            order_number=order.order_number,
        )

    try:
        cancel_customer_order(
            order=order,
            customer=request.customer,
            reason=form.cleaned_data["reason"],
            actor=request.user,
            request=request,
        )
    except PermissionDenied:
        # Should not happen after ownership 404 filter; treat as missing.
        from django.http import Http404

        raise Http404("Order not found.") from None
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return redirect(
            "orders:customer_order_detail",
            order_number=order.order_number,
        )

    messages.success(
        request,
        f"Order {order.order_number} has been cancelled.",
    )
    return redirect(
        "orders:customer_order_detail",
        order_number=order.order_number,
    )


# ---------------------------------------------------------------------------
# Store portal — StoreOrder management
# ---------------------------------------------------------------------------


@never_cache
@require_GET
@store_portal_required
def store_order_list_view(request):
    """List StoreOrders for request.store only."""
    store_orders = portal_store_orders_queryset(request.store)
    return render(
        request,
        "store_portal/orders/list.html",
        {
            "store_orders": store_orders,
            "can_manage_orders": store_user_can_manage_orders(request),
        },
    )


@never_cache
@require_GET
@store_portal_required
def store_order_detail_view(request, store_order_number):
    """
    StoreOrder detail for the logged-in store.

    Another store's store_order_number yields 404. Never trusts store_id from
    the client.
    """
    store_order = get_portal_store_order_or_404(
        request.store, store_order_number
    )
    can_manage = store_user_can_manage_orders(request)
    action_ctx = store_order_action_context(store_order)
    return render(
        request,
        "store_portal/orders/detail.html",
        {
            "store_order": store_order,
            "order": store_order.order,
            "items": store_order.items.all(),
            "status_history": store_order.status_history.all(),
            "can_manage_orders": can_manage,
            "reject_form": StoreOrderRejectForm(prefix="reject"),
            "note_form": StoreOrderStatusNoteForm(prefix="note"),
            **action_ctx,
        },
    )


def _store_order_action_redirect(store_order_number):
    return redirect(
        "orders:store_order_detail",
        store_order_number=store_order_number,
    )


@csrf_protect
@never_cache
@require_POST
@store_orders_manage_required
def store_order_accept_view(request, store_order_number):
    store_order = get_portal_store_order_or_404(
        request.store, store_order_number
    )
    form = StoreOrderStatusNoteForm(request.POST, prefix="note")
    if not form.is_valid():
        messages.error(request, "Invalid status update.")
        return _store_order_action_redirect(store_order.store_order_number)
    try:
        transition_store_order(
            store_order=store_order,
            store=request.store,
            action="accept",
            actor=request.user,
            reason=form.cleaned_data.get("reason") or "",
            request=request,
        )
    except PermissionDenied:
        from django.http import Http404

        raise Http404("Store order not found.") from None
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return _store_order_action_redirect(store_order.store_order_number)

    messages.success(
        request,
        f"Store order {store_order.store_order_number} accepted.",
    )
    return _store_order_action_redirect(store_order.store_order_number)


@csrf_protect
@never_cache
@require_POST
@store_orders_manage_required
def store_order_reject_view(request, store_order_number):
    store_order = get_portal_store_order_or_404(
        request.store, store_order_number
    )
    form = StoreOrderRejectForm(request.POST, prefix="reject")
    if not form.is_valid():
        for error in form.errors.get("reason", form.errors.get("__all__", [])):
            messages.error(request, error)
        return _store_order_action_redirect(store_order.store_order_number)
    try:
        transition_store_order(
            store_order=store_order,
            store=request.store,
            action="reject",
            actor=request.user,
            reason=form.cleaned_data["reason"],
            request=request,
        )
    except PermissionDenied:
        from django.http import Http404

        raise Http404("Store order not found.") from None
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return _store_order_action_redirect(store_order.store_order_number)

    messages.success(
        request,
        f"Store order {store_order.store_order_number} rejected.",
    )
    return _store_order_action_redirect(store_order.store_order_number)


@csrf_protect
@never_cache
@require_POST
@store_orders_manage_required
def store_order_processing_view(request, store_order_number):
    store_order = get_portal_store_order_or_404(
        request.store, store_order_number
    )
    form = StoreOrderStatusNoteForm(request.POST, prefix="note")
    if not form.is_valid():
        messages.error(request, "Invalid status update.")
        return _store_order_action_redirect(store_order.store_order_number)
    try:
        transition_store_order(
            store_order=store_order,
            store=request.store,
            action="processing",
            actor=request.user,
            reason=form.cleaned_data.get("reason") or "",
            request=request,
        )
    except PermissionDenied:
        from django.http import Http404

        raise Http404("Store order not found.") from None
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return _store_order_action_redirect(store_order.store_order_number)

    messages.success(
        request,
        f"Store order {store_order.store_order_number} marked as preparing.",
    )
    return _store_order_action_redirect(store_order.store_order_number)


@csrf_protect
@never_cache
@require_POST
@store_orders_manage_required
def store_order_ready_view(request, store_order_number):
    store_order = get_portal_store_order_or_404(
        request.store, store_order_number
    )
    form = StoreOrderStatusNoteForm(request.POST, prefix="note")
    if not form.is_valid():
        messages.error(request, "Invalid status update.")
        return _store_order_action_redirect(store_order.store_order_number)
    try:
        transition_store_order(
            store_order=store_order,
            store=request.store,
            action="ready",
            actor=request.user,
            reason=form.cleaned_data.get("reason") or "",
            request=request,
        )
    except PermissionDenied:
        from django.http import Http404

        raise Http404("Store order not found.") from None
    except ValidationError as exc:
        messages.error(request, _validation_message(exc))
        return _store_order_action_redirect(store_order.store_order_number)

    messages.success(
        request,
        f"Store order {store_order.store_order_number} marked as ready.",
    )
    return _store_order_action_redirect(store_order.store_order_number)
