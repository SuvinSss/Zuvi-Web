from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from accounts.decorators import can_access_management_portal, management_portal_required
from accounts.models import Role
from catalog.models import Product
from stores.decorators import store_portal_required

from .models import InventoryTransaction, PurchaseEntry

INVENTORY_VIEW_PERMISSIONS = (
    "inventory.view_inventorytransaction",
    "inventory.view_all_inventory",
)


def is_super_admin(user):
    return (
        user.is_authenticated
        and user.role == Role.SUPER_ADMIN
        and can_access_management_portal(user)
    )


def user_has_inventory_permission(user, permission):
    """Super Admins bypass; Admins must hold the Django permission."""
    if not can_access_management_portal(user):
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    return user.has_perm(permission)


def user_can_view_management_inventory(user):
    """
    Admin/Super Admin inventory page access.

    Requires view_inventorytransaction or view_all_inventory (Super Admin bypasses).
    """
    if not can_access_management_portal(user):
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    return any(user.has_perm(perm) for perm in INVENTORY_VIEW_PERMISSIONS)


def inventory_view_permission_required(view_func):
    """Require management portal access plus an inventory view permission."""

    @wraps(view_func)
    @management_portal_required
    def _wrapped_view(request, *args, **kwargs):
        if not user_can_view_management_inventory(request.user):
            raise PermissionDenied(
                "You do not have permission to view inventory."
            )
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def inventory_permission_required(permission):
    """Require management portal access plus a specific inventory permission."""

    def decorator(view_func):
        @wraps(view_func)
        @management_portal_required
        def _wrapped_view(request, *args, **kwargs):
            if not user_has_inventory_permission(request.user, permission):
                raise PermissionDenied(
                    "You do not have permission to perform this inventory action."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


def store_user_can_manage_inventory(request):
    membership = getattr(request, "store_membership", None)
    return bool(
        membership
        and membership.is_active
        and membership.can_manage_inventory
    )


def store_inventory_manage_required(view_func):
    """
    Store portal inventory mutations.

    Requires active store membership with can_manage_inventory=True.
    """

    @wraps(view_func)
    @store_portal_required
    def _wrapped_view(request, *args, **kwargs):
        if not store_user_can_manage_inventory(request):
            raise PermissionDenied(
                "You do not have permission to manage inventory for this store."
            )
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def management_products_queryset(user):
    """Products visible to a management-portal inventory actor."""
    queryset = Product.objects.select_related("store", "category").all()
    if is_super_admin(user) or user_has_inventory_permission(
        user, "inventory.view_all_inventory"
    ):
        return queryset
    # Admins with only view_inventorytransaction still see all products for MVP
    # listing; cross-store write isolation is enforced by action permissions.
    return queryset


def portal_inventory_products_queryset(request):
    store = getattr(request, "store", None)
    if store is None:
        return Product.objects.none()
    return Product.objects.filter(store_id=store.pk).select_related("store", "category")


def get_management_product_or_404(user, product_id):
    return get_object_or_404(management_products_queryset(user), pk=product_id)


def get_portal_inventory_product_or_404(request, product_id):
    return get_object_or_404(portal_inventory_products_queryset(request), pk=product_id)


def management_transactions_queryset(user):
    queryset = InventoryTransaction.objects.select_related(
        "store", "product", "created_by"
    )
    if is_super_admin(user) or user_has_inventory_permission(
        user, "inventory.view_all_inventory"
    ):
        return queryset
    return queryset


def portal_transactions_queryset(request):
    store = getattr(request, "store", None)
    if store is None:
        return InventoryTransaction.objects.none()
    return InventoryTransaction.objects.filter(store_id=store.pk).select_related(
        "store", "product", "created_by"
    )


def portal_purchase_entries_queryset(request):
    store = getattr(request, "store", None)
    if store is None:
        return PurchaseEntry.objects.none()
    return PurchaseEntry.objects.filter(store_id=store.pk).select_related("store")
