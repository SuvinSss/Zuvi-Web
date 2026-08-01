from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("customer/cart/", views.cart_detail_view, name="cart_detail"),
    path(
        "customer/cart/add/<str:product_code>/",
        views.cart_add_item_view,
        name="cart_add_item",
    ),
    path(
        "customer/cart/items/<int:pk>/update/",
        views.cart_update_item_view,
        name="cart_update_item",
    ),
    path(
        "customer/cart/items/<int:pk>/remove/",
        views.cart_remove_item_view,
        name="cart_remove_item",
    ),
    path("customer/cart/clear/", views.cart_clear_view, name="cart_clear"),
]
