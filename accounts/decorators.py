from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import Role

MANAGEMENT_ALLOWED_ROLES = {Role.SUPER_ADMIN, Role.ADMIN}


def can_access_management_portal(user):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.role == Role.SUPER_ADMIN:
        return user.is_staff and user.is_superuser
    if user.role == Role.ADMIN:
        return user.is_staff and not user.is_superuser
    return False


def management_portal_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                login_url=settings.LOGIN_URL,
            )

        if not can_access_management_portal(request.user):
            raise PermissionDenied("You are not allowed to access the management portal.")

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def super_admin_required(view_func):
    @wraps(view_func)
    @management_portal_required
    def _wrapped_view(request, *args, **kwargs):
        if not can_access_management_portal(request.user) or request.user.role != Role.SUPER_ADMIN:
            raise PermissionDenied("Only Super Admins can access this page.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
