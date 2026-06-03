from django.urls import path

from .views import (
    NotificationBrowserClientApiView,
    NotificationCenterView,
    NotificationDismissApiView,
    NotificationFeedApiView,
    NotificationMarkReadApiView,
    NotificationMarkSeenApiView,
    NotificationPreferencesApiView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationCenterView.as_view(), name="center"),
    path("api/feed/", NotificationFeedApiView.as_view(), name="api_feed"),
    path("api/mark-seen/", NotificationMarkSeenApiView.as_view(), name="api_mark_seen"),
    path("api/mark-read/", NotificationMarkReadApiView.as_view(), name="api_mark_read"),
    path("api/dismiss/", NotificationDismissApiView.as_view(), name="api_dismiss"),
    path("api/browser-client/", NotificationBrowserClientApiView.as_view(), name="api_browser_client"),
    path("api/preferences/", NotificationPreferencesApiView.as_view(), name="api_preferences"),
]
