from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from accounts.decorators import can_access_management_portal, management_portal_required
from accounts.models import Role

from .models import Store, StoreStatus, StoreUser
from .status import store_allows_portal_access


def is_super_admin(user):
    return (
        user.is_authenticated
        and user.role == Role.SUPER_ADMIN
        and can_access_management_portal(user)
    )


def user_has_store_permission(user, permission):
    """
    Super Admins bypass store permission checks.
    Admins must hold the given Django permission.
    """
    if not can_access_management_portal(user):
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    return user.has_perm(permission)


def store_permission_required(permission):
    """Require management portal access plus a Store-related Django permission."""

    def decorator(view_func):
        @wraps(view_func)
        @management_portal_required
        def _wrapped_view(request, *args, **kwargs):
            if not user_has_store_permission(request.user, permission):
                raise PermissionDenied(
                    "You do not have permission to perform this store action."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


def resolve_store_portal_membership(user):
    """
    Resolve the caller's store-portal membership.

    Returns (membership, denial_message). membership is None when access is denied.
    Never trusts a client-supplied store_id.
    """
    if not user or not user.is_authenticated:
        return None, "Authentication required."
    if not user.is_active:
        return None, "This account is inactive."
    if user.role != Role.STORE_USER:
        return None, "Only Store Users can access the store portal."

    membership = (
        StoreUser.objects.select_related(
            "store",
            "store__address",
            "store__category",
            "user",
        )
        .filter(user=user, is_active=True)
        .first()
    )
    if membership is None:
        return None, "No active store membership found for this account."

    store = membership.store
    if not store.is_active:
        return None, "This store is inactive. Portal access is blocked."

    if store.status != StoreStatus.ACTIVE:
        status_messages = {
            StoreStatus.PENDING: "This store is still pending approval.",
            StoreStatus.REJECTED: "This store was rejected and cannot access the portal.",
            StoreStatus.SUSPENDED: "This store is suspended. Portal access is blocked.",
        }
        return None, status_messages.get(
            store.status,
            "This store cannot access the store portal.",
        )
    if not store_allows_portal_access(store):
        return None, "This store cannot access the store portal."
    return membership, None


def portal_stores_queryset(user):
    """Store queryset strictly limited to the caller's assigned store."""
    membership, _ = resolve_store_portal_membership(user)
    if membership is None:
        return Store.objects.none()
    return Store.objects.filter(pk=membership.store_id).select_related(
        "address",
        "category",
    )


def get_portal_store_or_404(user, store_id=None):
    """
    Fetch a store for portal use.

    If store_id is provided it must match the caller's membership store;
    otherwise the membership store is returned. Client-supplied IDs for other
    stores raise Http404.
    """
    queryset = portal_stores_queryset(user)
    if store_id is None:
        store = queryset.first()
        if store is None:
            raise PermissionDenied("No accessible store found for this account.")
        return store
    return get_object_or_404(queryset, pk=store_id)


def attach_store_portal_context(request):
    membership, denial = resolve_store_portal_membership(request.user)
    if membership is None:
        raise PermissionDenied(denial or "Store portal access denied.")
    request.store_membership = membership
    request.store = membership.store
    return membership


def store_portal_required(view_func):
    """
    Protect store-portal operations.

    Requires an authenticated, active STORE_USER with an active StoreUser
    membership whose Store is ACTIVE and is_active=True.
    """

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=getattr(settings, "STORE_LOGIN_URL", "/store/login/"),
            )
        attach_store_portal_context(request)
        return view_func(request, *args, **kwargs)

    return _wrapped_view


class StorePortalRequiredMixin:
    """Class-based-view mixin mirroring store_portal_required."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=getattr(settings, "STORE_LOGIN_URL", "/store/login/"),
            )
        attach_store_portal_context(request)
        return super().dispatch(request, *args, **kwargs)
