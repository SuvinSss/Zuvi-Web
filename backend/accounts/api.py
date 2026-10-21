"""Session authentication for the React management app (``/api/v1/auth/``).

Django session cookies (HttpOnly, database-backed) are the only credential: no
tokens are issued or stored in browser storage. CSRF stays enforced; the client
reads the ``csrftoken`` cookie set by ``GET /auth/session/`` and sends it back
in ``X-CSRFToken``.
"""
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from catalog.decorators import user_has_catalog_permission

from .decorators import can_access_management_portal


def user_payload(user):
    return {
        "id": user.pk, "username": user.get_username(), "email": user.email,
        "name": user.get_full_name() or user.get_username(), "role": user.role,
        "permissions": {
            perm: user_has_catalog_permission(user, f"catalog.{perm}_product")
            for perm in ("view", "add", "change")
        },
    }


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    """Restore the session after a page refresh and hand the client a CSRF cookie."""

    # Safe method + session auth: yields the session user (or anonymous) without CSRF checks.
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @extend_schema(responses=dict)
    def get(self, request):
        user = request.user
        if user.is_authenticated and can_access_management_portal(user):
            return Response({"authenticated": True, "user": user_payload(user), "csrf_token": get_token(request._request)})
        return Response({"authenticated": False, "user": None, "csrf_token": get_token(request._request)})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, responses=dict)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        form = AuthenticationForm(request._request, data=serializer.validated_data)
        if not form.is_valid():
            return Response({"detail": "Invalid username or password."}, status=status.HTTP_400_BAD_REQUEST)
        user = form.get_user()
        if not can_access_management_portal(user):
            return Response({"detail": "This account cannot access the management portal."},
                            status=status.HTTP_403_FORBIDDEN)
        login(request._request, user)  # rotates the session key
        # login() rotates the CSRF token; return the new one for clients that cannot read the cookie.
        return Response({"authenticated": True, "user": user_payload(user), "csrf_token": get_token(request._request)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request._request)  # flushes the server-side session
        return Response(status=status.HTTP_204_NO_CONTENT)
