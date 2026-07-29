from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    # Management — taxonomy
    path(
        "management/product-categories/",
        views.category_list_view,
        name="category_list",
    ),
    path(
        "management/product-categories/create/",
        views.category_create_view,
        name="category_create",
    ),
    path(
        "management/product-categories/<int:pk>/edit/",
        views.category_edit_view,
        name="category_edit",
    ),
    path("management/brands/", views.brand_list_view, name="brand_list"),
    path("management/brands/create/", views.brand_create_view, name="brand_create"),
    path(
        "management/brands/<int:pk>/edit/",
        views.brand_edit_view,
        name="brand_edit",
    ),
    path("management/tags/", views.tag_list_view, name="tag_list"),
    path("management/tags/create/", views.tag_create_view, name="tag_create"),
    path("management/tags/<int:pk>/edit/", views.tag_edit_view, name="tag_edit"),
    # Management — products
    path("management/products/", views.product_list_view, name="product_list"),
    path(
        "management/products/create/",
        views.product_create_view,
        name="product_create",
    ),
    path(
        "management/products/<int:pk>/",
        views.product_detail_view,
        name="product_detail",
    ),
    path(
        "management/products/<int:pk>/edit/",
        views.product_edit_view,
        name="product_edit",
    ),
    path(
        "management/products/<int:pk>/pricing/",
        views.product_pricing_view,
        name="product_pricing",
    ),
    path(
        "management/products/<int:pk>/change-status/",
        views.product_change_status_view,
        name="product_change_status",
    ),
    path(
        "management/products/<int:pk>/images/",
        views.product_images_view,
        name="product_images",
    ),
    path(
        "management/products/<int:pk>/images/<int:image_id>/delete/",
        views.product_image_delete_view,
        name="product_image_delete",
    ),
    path(
        "management/products/<int:pk>/images/<int:image_id>/set-primary/",
        views.product_image_set_primary_view,
        name="product_image_set_primary",
    ),
    # Store portal
    path("store/products/", views.store_product_list_view, name="store_product_list"),
    path(
        "store/products/create/",
        views.store_product_create_view,
        name="store_product_create",
    ),
    path(
        "store/products/<int:pk>/",
        views.store_product_detail_view,
        name="store_product_detail",
    ),
    path(
        "store/products/<int:pk>/edit/",
        views.store_product_edit_view,
        name="store_product_edit",
    ),
    path(
        "store/products/<int:pk>/submit/",
        views.store_product_submit_view,
        name="store_product_submit",
    ),
    path(
        "store/products/<int:pk>/images/",
        views.store_product_images_view,
        name="store_product_images",
    ),
    path(
        "store/products/<int:pk>/images/<int:image_id>/delete/",
        views.store_product_image_delete_view,
        name="store_product_image_delete",
    ),
    path(
        "store/products/<int:pk>/images/<int:image_id>/set-primary/",
        views.store_product_image_set_primary_view,
        name="store_product_image_set_primary",
    ),
]
