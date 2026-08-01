from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

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
    remove_cart_item,
    update_cart_item_quantity,
)


def _customer_login_url():
    return getattr(settings, "CUSTOMER_LOGIN_URL", "/customer/login/")


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


@never_cache
@customer_portal_required
def cart_detail_view(request):
    """Display the authenticated customer's cart grouped by store."""
    # Ownership from request.customer (authenticated profile) — ignore cart_id.
    context = build_cart_view_context(request.customer)
    return render(request, "cart/cart_detail.html", context)


@csrf_protect
@never_cache
@require_POST
def cart_add_item_view(request, product_code):
    """
    Add a product to the authenticated customer's cart by product_code.

    Anonymous shoppers are redirected to customer login and returned to the
    product detail page after login (they must submit Add to Cart again).
    """
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
        return redirect_to_login(next_url, login_url=_customer_login_url())

    customer, denial = resolve_customer_portal_profile(request.user)
    if customer is None:
        if getattr(request.user, "role", None) != Role.CUSTOMER:
            messages.error(request, "Only customers can add items to a cart.")
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
        messages.error(request, _validation_message(exc))
        return _product_detail_redirect(product_code=product_code)

    messages.success(
        request,
        f"Added {item.quantity} × {item.product.name} to your cart.",
    )
    return redirect("cart:cart_detail")


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def cart_update_item_view(request, pk):
    customer = request.customer
    item = get_portal_cart_item_or_404(customer, pk)
    form = CartItemQuantityForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid quantity greater than zero.")
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
        messages.error(request, _validation_message(exc))
        return redirect("cart:cart_detail")

    messages.success(request, "Cart updated.")
    return redirect("cart:cart_detail")


@csrf_protect
@never_cache
@require_POST
@customer_portal_required
def cart_remove_item_view(request, pk):
    customer = request.customer
    # 404 if the item belongs to another customer.
    item = get_portal_cart_item_or_404(customer, pk)
    try:
        remove_cart_item(customer=customer, cart_item_id=item.pk)
    except CartItem.DoesNotExist as exc:
        raise Http404("Cart item not found.") from exc

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
