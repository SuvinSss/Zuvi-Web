"""Decorators for store-portal and management-portal order access."""

from functools import wraps

from django.core.exceptions import PermissionDenied

from accounts.decorators import can_access_management_portal, management_portal_required
from accounts.models import Role
from stores.decorators import store_portal_required


def store_user_can_manage_orders(request):
    membership = getattr(request, "store_membership", None)
    return bool(
        membership
        and membership.is_active
        and membership.can_manage_orders
    )


def store_orders_manage_required(view_func):
    """
    Store portal order mutations.

    Requires active store membership with can_manage_orders=True.
    Suspended/inactive stores are already blocked by store_portal_required.
    """

    @wraps(view_func)
    @store_portal_required
    def _wrapped_view(request, *args, **kwargs):
        if not store_user_can_manage_orders(request):
            raise PermissionDenied(
                "You do not have permission to manage orders for this store."
            )
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def user_has_order_permission(user, permission):
    """
    Super Admins bypass order permission checks.
    Admins must hold the given Django permission.
    Store Users, Customers and other roles never receive management access.
    """
    if not can_access_management_portal(user):
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    if user.role != Role.ADMIN:
        return False
    return user.has_perm(permission)


def order_permission_required(permission):
    """Require management portal access plus an order-related Django permission."""

    def decorator(view_func):
        @wraps(view_func)
        @management_portal_required
        def _wrapped_view(request, *args, **kwargs):
            if not user_has_order_permission(request.user, permission):
                raise PermissionDenied(
                    "You do not have permission to perform this order action."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
