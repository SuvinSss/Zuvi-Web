from customers.decorators import resolve_customer_portal_profile

from .services import get_cart_item_count


def cart_summary(request):
    """Expose the shopper's live cart item count to every template."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"cart_item_count": 0}

    customer, _denial = resolve_customer_portal_profile(user)
    if customer is None:
        return {"cart_item_count": 0}

    return {"cart_item_count": get_cart_item_count(customer)}
