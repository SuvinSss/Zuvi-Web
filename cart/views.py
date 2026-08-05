from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Role
from catalog.models import Product
from catalog.public import public_products_queryset
from customers.decorators import (
    customer_portal_required,
    resolve_customer_portal_profile,
)

from .forms import CartItemQuantityForm
from .models import CartItem
from .services import (
    add_product_to_cart,
    build_cart_view_context,
    clear_cart,
    get_portal_cart_item_or_404,
    list_cart_lines_summary,
    remove_cart_item,
    update_cart_item_quantity,
)


def _customer_login_url():
    return getattr(settings, "CUSTOMER_LOGIN_URL", "/customer/login/")


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _validation_message(exc):
    if hasattr(exc, "message_dict"):
        first = next(iter(exc.message_dict.values()))
        return first[0] if isinstance(first, list) else first
    return "; ".join(exc.messages)


def _product_detail_redirect(product_code=None):
    """Prefer the public product page; fall back to the catalogue list."""
    if product_code:
        slug = (
            public_products_queryset()
            .filter(product_code=product_code)
            .values_list("slug", flat=True)
            .first()
        )
        if slug:
            return redirect("catalog:public_product_detail", slug=slug)
    return redirect("catalog:public_product_list")


def _ajax_cart_state(customer, *, item_pk=None):
    """Build the JSON payload mutation endpoints return for AJAX callers."""
    context = build_cart_view_context(customer)
    store_subtotals = {
        str(group["store_id"]): str(group["preview_subtotal"])
        for group in context["store_groups"]
    }
    item_payload = None
    if item_pk is not None:
        for group in context["store_groups"]:
            for row in group["items"]:
                if row["item"].pk == item_pk:
                    item_payload = {
                        "cart_item_id": item_pk,
                        "quantity": str(row["quantity"]),
                        "unit_price": (
                            str(row["unit_price"])
                            if row["unit_price"] is not None
                            else None
                        ),
                        "line_total": (
                            str(row["line_total"])
                            if row["line_total"] is not None
                            else None
                        ),
                        "warnings": row["warnings"],
                    }
                    break
            if item_payload:
                break
    return {
        "ok": True,
        "item_count": context["item_count"],
        "preview_subtotal": str(context["preview_subtotal"]),
        "store_subtotals": store_subtotals,
        "item": item_payload,
        "is_empty": context["is_empty"],
    }


@never_cache
@customer_portal_required
def cart_detail_view(request):
    """Display the authenticated customer's cart grouped by store."""
    # Ownership from request.customer (authenticated profile) — ignore cart_id.
    context = build_cart_view_context(request.customer)
    if _is_ajax(request):
        # Fetched after a stepper/remove action to refresh #cartContent in place.
        return render(request, "cart/includes/_cart_content.html", context)
    return render(request, "cart/cart_detail.html", context)


@never_cache
@customer_portal_required
def cart_mini_view(request):
    """Render the compact mini-cart drawer body for the authenticated customer."""
    context = build_cart_view_context(request.customer)
    return render(request, "cart/includes/_mini_cart_body.html", context)


@require_GET
@never_cache
def cart_summary_view(request):
    """
    Lightweight JSON cart snapshot for hydrating storefront pages.

    Degrades to an empty cart for anonymous/non-customer visitors instead of
    redirecting to login, since this is polled opportunistically.
    """
    empty_response = {"item_count": 0, "preview_subtotal": "0.00", "lines": []}
    if not request.user.is_authenticated:
        return JsonResponse(empty_response)

    customer, _denial = resolve_customer_portal_profile(request.user)
    if customer is None:
        return JsonResponse(empty_response)

    lines = list_cart_lines_summary(customer)
    context = build_cart_view_context(customer)
    return JsonResponse(
        {
            "item_count": context["item_count"],
            "preview_subtotal": str(context["preview_subtotal"]),
            "lines": [
                {
                    "product_code": product_code,
                    "cart_item_id": cart_item_id,
                    "quantity": str(quantity),
                }
                for product_code, cart_item_id, quantity in lines
            ],
        }
    )


@csrf_protect
@never_cache
@require_POST
def cart_add_item_view(request, product_code):
    """
    Add a product to the authenticated customer's cart by product_code.

    Anonymous shoppers are redirected to customer login and returned to the
    product detail page after login (they must submit Add to Cart again).
    """
    ajax = _is_ajax(request)

    if not request.user.is_authenticated:
        product = (
            Product.objects.filter(product_code=product_code).only("slug").first()
        )
        if product:
            next_url = reverse(
                "catalog:public_product_detail",
                kwargs={"slug": product.slug},
            )
        else:
            next_url = reverse("catalog:public_product_list")
        response = redirect_to_login(next_url, login_url=_customer_login_url())
        if ajax:
            return JsonResponse(
                {"ok": False, "login_required": True, "redirect": response.url},
                status=401,
            )
        return response

    customer, denial = resolve_customer_portal_profile(request.user)
    if customer is None:
        if getattr(request.user, "role", None) != Role.CUSTOMER:
            message = "Only customers can add items to a cart."
            if ajax:
                return JsonResponse({"ok": False, "error": message}, status=403)
            messages.error(request, message)
            return redirect("catalog:public_product_list")
        raise PermissionDenied(denial or "Customer portal access denied.")
    request.customer = customer

    quantity = request.POST.get("quantity", "1")
    # Never accept customer_id / cart_id from the form.
    try:
        item = add_product_to_cart(
            customer=customer,
            product_code=product_code,
            quantity=quantity,
        )
    except ValidationError as exc:
        message = _validation_message(exc)
        if ajax:
            return JsonResponse({"ok": False, "error": message}, status=400)
        messages.error(request, message)
        return _product_detail_redirect(product_code=product_code)

    if ajax:
        data = _ajax_cart_state(customer, item_pk=item.pk)
        data["cart_item_id"] = item.pk
        data["quantity"] = str(item.quantity)
        data["product_code"] = product_code
        return JsonResponse(data)

    messages.success(
        request,
        f"Added {item.quantity} × {item.product.name} to your cart.",
    )
    if request.POST.get("redirect_to") == "checkout":
        return redirect("orders:checkout_preview")
    return redirect("cart:cart_detail")


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def cart_update_item_view(request, pk):
    ajax = _is_ajax(request)
    customer = request.customer
    item = get_portal_cart_item_or_404(customer, pk)
    form = CartItemQuantityForm(request.POST)
    if not form.is_valid():
        message = "Enter a valid quantity greater than zero."
        if ajax:
            return JsonResponse({"ok": False, "error": message}, status=400)
        messages.error(request, message)
        return redirect("cart:cart_detail")

    try:
        update_cart_item_quantity(
            customer=customer,
            cart_item_id=item.pk,
            quantity=form.cleaned_data["quantity"],
        )
    except CartItem.DoesNotExist as exc:
        raise Http404("Cart item not found.") from exc
    except ValidationError as exc:
        message = _validation_message(exc)
        if ajax:
            return JsonResponse({"ok": False, "error": message}, status=400)
        messages.error(request, message)
        return redirect("cart:cart_detail")

    if ajax:
        return JsonResponse(_ajax_cart_state(customer, item_pk=item.pk))

    messages.success(request, "Cart updated.")
    return redirect("cart:cart_detail")


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def cart_remove_item_view(request, pk):
    ajax = _is_ajax(request)
    customer = request.customer
    # 404 if the item belongs to another customer.
    item = get_portal_cart_item_or_404(customer, pk)
    try:
        remove_cart_item(customer=customer, cart_item_id=item.pk)
    except CartItem.DoesNotExist as exc:
        raise Http404("Cart item not found.") from exc

    if ajax:
        return JsonResponse(_ajax_cart_state(customer))

    messages.success(request, "Item removed from your cart.")
    return redirect("cart:cart_detail")


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def cart_clear_view(request):
    clear_cart(customer=request.customer)
    messages.success(request, "Your cart has been cleared.")
    return redirect("cart:cart_detail")
