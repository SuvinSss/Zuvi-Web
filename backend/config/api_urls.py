"""Versioned REST API root: /api/v1/."""
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import IsAuthenticated

from accounts import api as auth_api

urlpatterns = [
    path("auth/session/", auth_api.SessionView.as_view(), name="api_auth_session"),
    path("auth/login/", auth_api.LoginView.as_view(), name="api_auth_login"),
    path("auth/logout/", auth_api.LogoutView.as_view(), name="api_auth_logout"),
    path("schema/", SpectacularAPIView.as_view(permission_classes=[IsAuthenticated]), name="api_schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_schema", permission_classes=[IsAuthenticated]), name="api_docs"),
    path("", include("notifications.urls")),
    path("", include("deliveries.urls")),
    path("", include("catalog.api.urls")),
]
