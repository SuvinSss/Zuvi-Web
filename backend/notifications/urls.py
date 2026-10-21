from django.urls import path

from . import api

urlpatterns = [
    path("notifications/", api.NotificationListView.as_view(), name="api_notifications"),
    path("notifications/unread-count/", api.UnreadCountView.as_view(), name="api_notifications_unread"),
    path("notifications/read-all/", api.NotificationReadAllView.as_view(), name="api_notifications_read_all"),
    path("notifications/preferences/", api.PreferenceView.as_view(), name="api_notifications_prefs"),
    path("notifications/<int:pk>/read/", api.NotificationReadView.as_view(), name="api_notification_read"),
]
