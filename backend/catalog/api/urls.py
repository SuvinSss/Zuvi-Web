from django.urls import path

from . import views

urlpatterns = [
    path("products/", views.ProductListCreateView.as_view(), name="api_product_list"),
    path("products/meta/", views.ProductMetaView.as_view(), name="api_product_meta"),
    path("products/import/template/", views.ImportTemplateView.as_view(), name="api_import_template"),
    path("products/import/preview/", views.ImportPreviewView.as_view(), name="api_import_preview"),
    path("products/import/<uuid:batch_id>/", views.ImportDetailView.as_view(), name="api_import_detail"),
    path("products/import/<uuid:batch_id>/commit/", views.ImportCommitView.as_view(), name="api_import_commit"),
    path("products/import/<uuid:batch_id>/errors/", views.ImportErrorReportView.as_view(), name="api_import_errors"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="api_product_detail"),
    path("products/<int:pk>/images/", views.ProductImagesView.as_view(), name="api_product_images"),
    path("products/<int:pk>/images/<int:image_id>/", views.ProductImageDetailView.as_view(), name="api_product_image"),
    path("products/<int:pk>/images/<int:image_id>/primary/", views.ProductImagePrimaryView.as_view(), name="api_product_image_primary"),
    path("products/<int:pk>/image-suggestions/", views.ImageSuggestionsView.as_view(), name="api_image_suggestions"),
]
