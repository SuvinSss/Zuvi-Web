from django.urls import path

from . import views

app_name = "stores"

urlpatterns = [
    path("management/stores/", views.store_list_view, name="store_list"),
    path("management/stores/create/", views.store_create_view, name="store_create"),
    path("management/stores/<int:pk>/", views.store_detail_view, name="store_detail"),
    path("management/stores/<int:pk>/edit/", views.store_edit_view, name="store_edit"),
    path(
        "management/stores/<int:pk>/change-status/",
        views.store_change_status_view,
        name="store_change_status",
    ),
    path(
        "management/stores/<int:pk>/users/",
        views.store_user_list_view,
        name="store_user_list",
    ),
    path(
        "management/stores/<int:pk>/users/create/",
        views.store_user_create_view,
        name="store_user_create",
    ),
    path(
        "management/stores/<int:pk>/users/<int:user_id>/edit/",
        views.store_user_edit_view,
        name="store_user_edit",
    ),
    path(
        "management/stores/<int:pk>/users/<int:user_id>/toggle-status/",
        views.store_user_toggle_status_view,
        name="store_user_toggle_status",
    ),
    path("store/login/", views.store_portal_login_view, name="store_portal_login"),
    path("store/logout/", views.store_portal_logout_view, name="store_portal_logout"),
    path(
        "store/dashboard/",
        views.store_portal_dashboard_view,
        name="store_portal_dashboard",
    ),
    path(
        "store/profile/",
        views.store_portal_profile_view,
        name="store_portal_profile",
    ),
]
