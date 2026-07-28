from django.urls import path

from .views import (
    admin_create_view,
    admin_detail_view,
    admin_edit_view,
    admin_list_view,
    admin_toggle_status_view,
    management_dashboard_view,
    management_login_view,
    management_logout_view,
)

app_name = "accounts"

urlpatterns = [
    path("management/login/", management_login_view, name="management_login"),
    path("management/logout/", management_logout_view, name="management_logout"),
    path("management/dashboard/", management_dashboard_view, name="management_dashboard"),
    path("management/admins/", admin_list_view, name="admin_list"),
    path("management/admins/create/", admin_create_view, name="admin_create"),
    path("management/admins/<int:pk>/", admin_detail_view, name="admin_detail"),
    path("management/admins/<int:pk>/edit/", admin_edit_view, name="admin_edit"),
    path(
        "management/admins/<int:pk>/toggle-status/",
        admin_toggle_status_view,
        name="admin_toggle_status",
    ),
]
