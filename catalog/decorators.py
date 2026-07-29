from functools import wraps

from django.core.exceptions import PermissionDenied

from accounts.decorators import can_access_management_portal, management_portal_required
from accounts.models import Role


def is_super_admin(user):
    return (
        user.is_authenticated
        and user.role == Role.SUPER_ADMIN
        and can_access_management_portal(user)
    )


def user_has_catalog_permission(user, permission):
    """
    Super Admins bypass catalog permission checks.
    Admins must hold the given Django permission.
    """
    if not can_access_management_portal(user):
        return False
    if user.role == Role.SUPER_ADMIN:
        return True
    return user.has_perm(permission)


def catalog_permission_required(permission):
    """Require management portal access plus a catalog-related Django permission."""

    def decorator(view_func):
        @wraps(view_func)
        @management_portal_required
        def _wrapped_view(request, *args, **kwargs):
            if not user_has_catalog_permission(request.user, permission):
                raise PermissionDenied(
                    "You do not have permission to perform this product action."
                )
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
