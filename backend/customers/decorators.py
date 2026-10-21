from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from accounts.decorators import can_access_management_portal, management_portal_required
from accounts.models import Role

from .models import Customer, CustomerAddress


def is_super_admin(user):
    return (
        user.is_authenticated
        and user.role == Role.SUPER_ADMIN
        and can_access_management_portal(user)
    )


def user_has_customer_permission(user, permission):
    """
    Super Admins bypass customer permission checks.
    Admins must hold the given Django permission.
    Customers and other roles never receive management access here.
    """
    if not can_access_management_portal(user):
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    if user.role != Role.ADMIN:
        return False
    return user.has_perm(permission)


def customer_permission_required(permission):
    """Require management portal access plus a customer-related Django permission."""

    def decorator(view_func):
        @wraps(view_func)
        @management_portal_required
        def _wrapped_view(request, *args, **kwargs):
            if not user_has_customer_permission(request.user, permission):
                raise PermissionDenied(
                    "You do not have permission to perform this customer action."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


def resolve_customer_portal_profile(user):
    """
    Resolve the caller's customer-portal profile.

    Returns (customer, denial_message). customer is None when access is denied.
    """
    if not user or not user.is_authenticated:
        return None, "Authentication required."
    if not user.is_active:
        return None, "This account is inactive."
    if user.role != Role.CUSTOMER:
        return None, "Only Customers can access the customer portal."

    try:
        customer = user.customer_profile
    except Customer.DoesNotExist:
        return None, "No customer profile found for this account."

    return customer, None


def can_access_customer_portal(user):
    customer, _ = resolve_customer_portal_profile(user)
    return customer is not None


def attach_customer_portal_context(request):
    customer, denial = resolve_customer_portal_profile(request.user)
    if customer is None:
        raise PermissionDenied(denial or "Customer portal access denied.")
    request.customer = customer
    return customer


def customer_portal_required(view_func):
    """
    Protect customer-portal operations.

    Requires an authenticated, active CUSTOMER user with a Customer profile.
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=getattr(settings, "CUSTOMER_LOGIN_URL", "/customer/login/"),
            )
        attach_customer_portal_context(request)
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def portal_customer_addresses_queryset(user):
    """
    CustomerAddress queryset strictly limited to the authenticated user's Customer.

    Never trusts a client-supplied customer_id.
    """
    return CustomerAddress.objects.filter(customer__user_id=user.pk).select_related(
        "address",
        "customer",
        "customer__user",
    )


def get_portal_customer_address_or_404(user, pk):
    """Return an address owned by the authenticated customer, or 404."""
    return get_object_or_404(portal_customer_addresses_queryset(user), pk=pk)
