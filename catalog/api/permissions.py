from rest_framework.permissions import BasePermission

from catalog.decorators import user_has_catalog_permission

ACTION_PERMISSIONS = {
    "GET": "catalog.view_product", "HEAD": "catalog.view_product", "OPTIONS": "catalog.view_product",
    "POST": "catalog.add_product", "PATCH": "catalog.change_product", "PUT": "catalog.change_product",
    "DELETE": "catalog.change_product",
}


class CatalogManagementPermission(BasePermission):
    """Management portal users holding the matching Django catalog permission.

    Super Admins pass; Admins need the explicit permission. Store users and
    customers never reach these endpoints (enforced here, not in the UI).
    """

    def has_permission(self, request, view):
        perm = getattr(view, "required_permission", None) or ACTION_PERMISSIONS.get(request.method)
        return bool(perm and request.user.is_authenticated and user_has_catalog_permission(request.user, perm))
