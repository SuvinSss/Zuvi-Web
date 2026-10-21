from django.urls import path

from . import api

urlpatterns = [
    path("feedback/", api.FeedbackListCreateView.as_view(), name="api_feedback"),
    path("feedback/<int:pk>/", api.FeedbackDetailView.as_view(), name="api_feedback_detail"),
    path("feedback/<int:pk>/replies/", api.ReplyView.as_view(), name="api_feedback_reply"),
    path("feedback/<int:pk>/status/", api.StatusView.as_view(), name="api_feedback_status"),
    path("feedback/<int:pk>/escalate/", api.EscalateView.as_view(), name="api_feedback_escalate"),
]
