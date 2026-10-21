from django.urls import path

from . import api

urlpatterns = [
    path("public/stores/<int:pk>/reviews/", api.StoreReviewsView.as_view(), name="api_public_store_reviews"),
    path("public/products/<int:pk>/reviews/", api.ProductReviewsView.as_view(), name="api_public_product_reviews"),
    path("reviews/", api.CreateReviewView.as_view(), name="api_review_create"),
    path("reviews/mine/", api.MyReviewsView.as_view(), name="api_reviews_mine"),
    path("reviews/<int:pk>/", api.MyReviewDetailView.as_view(), name="api_review_detail"),
    path("reviews/<int:pk>/report/", api.ReportReviewView.as_view(), name="api_review_report"),
    path("store/reviews/", api.StoreReviewListView.as_view(), name="api_store_reviews"),
    path("store/reviews/<int:pk>/reply/", api.StoreReplyView.as_view(), name="api_store_review_reply"),
    path("delivery/ratings/", api.PartnerRatingsView.as_view(), name="api_partner_ratings"),
    path("admin/reviews/", api.AdminReviewListView.as_view(), name="api_admin_reviews"),
    path("admin/reviews/<int:pk>/hide/", api.HideView.as_view(), name="api_admin_review_hide"),
    path("admin/reviews/<int:pk>/reject/", api.RejectView.as_view(), name="api_admin_review_reject"),
    path("admin/reviews/<int:pk>/restore/", api.RestoreView.as_view(), name="api_admin_review_restore"),
]
