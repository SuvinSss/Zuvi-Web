"""Role permissions for the JSON API.

Every check resolves the caller's identity from the session. No identifier of a
customer, store or rider is ever accepted from the client as proof of identity.
"""

from rest_framework.permissions import BasePermission

from accounts.decorators import can_access_management_portal
from accounts.models import Role
from customers.decorators import resolve_customer_portal_profile
from stores.decorators import resolve_store_portal_membership


class IsCustomer(BasePermission):
    message = "Only customers can do this."

    def has_permission(self, request, view):
        customer, _ = resolve_customer_portal_profile(request.user)
        if customer is None:
            return False
        request.customer = customer
        return True


class IsStoreUser(BasePermission):
    message = "Only store users can do this."

    def has_permission(self, request, view):
        membership, _ = resolve_store_portal_membership(request.user)
        if membership is None:
            return False
        request.store_membership = membership
        request.store = membership.store
        return True


class IsDeliveryAgent(BasePermission):
    message = "Only delivery partners can do this."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active and user.role == Role.DELIVERY_AGENT
        )


def user_has_geo_permission(user, permission):
    if not can_access_management_portal(user):
        return False
    return user.role == Role.SUPER_ADMIN or user.has_perm(permission)


class HasGeoPermission(BasePermission):
    """Subclass and set ``permission``. Super Admins pass; Admins need the permission."""

    permission = ""
    message = "You do not have permission to do this."

    def has_permission(self, request, view):
        return user_has_geo_permission(request.user, self.permission)


class CanManageMaps(HasGeoPermission):
    permission = "geo.manage_maps_operations"


class CanManagePricing(HasGeoPermission):
    permission = "geo.manage_delivery_pricing"


class CanManageAssignments(HasGeoPermission):
    permission = "geo.manage_delivery_assignments"
