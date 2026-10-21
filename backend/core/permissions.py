"""Role and object-level permission classes shared by every API module.

Every check is server-side. A request's store, customer or delivery profile is
always resolved from ``request.user`` - never from a client-supplied id.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.decorators import can_access_management_portal
from accounts.models import Role

SUPPORT_ROLES = {Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR}


def is_management(user) -> bool:
    return bool(user and user.is_authenticated and can_access_management_portal(user))


def is_support_staff(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.role in SUPPORT_ROLES)


def is_support_supervisor(user) -> bool:
    return bool(
        user and user.is_authenticated and user.is_active
        and (user.role == Role.SUPPORT_SUPERVISOR or is_management(user))
    )


def get_customer(user):
    """Active customer profile or None."""
    if not (user and user.is_authenticated and user.is_active and user.role == Role.CUSTOMER):
        return None
    return getattr(user, "customer_profile", None)


def get_store_membership(user):
    from stores.decorators import resolve_store_portal_membership

    membership, _denial = resolve_store_portal_membership(user)
    return membership


def get_delivery_partner(user, *, approved_only=True):
    if not (user and user.is_authenticated and user.is_active and user.role == Role.DELIVERY_AGENT):
        return None
    partner = getattr(user, "delivery_partner", None)
    if partner is None:
        return None
    if approved_only and not partner.is_approved:
        return None
    return partner


class IsCustomer(BasePermission):
    message = "Only customers can use this endpoint."

    def has_permission(self, request, view):
        return get_customer(request.user) is not None


class IsStoreUser(BasePermission):
    message = "An active store membership is required."

    def has_permission(self, request, view):
        return get_store_membership(request.user) is not None


class IsStoreOrderManager(BasePermission):
    """Store users who may accept/reject/progress orders (StoreUser.can_manage_orders)."""

    message = "You do not have permission to manage orders for this store."

    def has_permission(self, request, view):
        membership = get_store_membership(request.user)
        return bool(membership and membership.can_manage_orders)


class IsDeliveryPartner(BasePermission):
    message = "An approved delivery partner account is required."

    def has_permission(self, request, view):
        return get_delivery_partner(request.user) is not None


class IsDeliveryPartnerProfile(BasePermission):
    """Delivery partners that may exist but are not yet approved (onboarding endpoints)."""

    def has_permission(self, request, view):
        return get_delivery_partner(request.user, approved_only=False) is not None


class IsSupportStaff(BasePermission):
    message = "Support staff access is required."

    def has_permission(self, request, view):
        return is_support_staff(request.user) or is_management(request.user)


class IsSupportSupervisor(BasePermission):
    message = "Support supervisor access is required."

    def has_permission(self, request, view):
        return is_support_supervisor(request.user)


class IsManagement(BasePermission):
    message = "Administrator access is required."

    def has_permission(self, request, view):
        return is_management(request.user)


class IsManagementOrReadOnlyAuthenticated(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or is_management(request.user)
