from django.urls import path

from .views import (
    NotificationBrowserClientApiView,
    NotificationCenterView,
    NotificationDeviceAckApiView,
    NotificationDeviceExchangeCodeApiView,
    NotificationDeviceFeedApiView,
    NotificationDeviceLinkCodeCreateView,
    NotificationDeviceRevokeApiView,
    NotificationDeviceRevokeView,
    NotificationDevicesView,
    NotificationDismissApiView,
    NotificationFeedApiView,
    NotificationMarkReadApiView,
    NotificationMarkSeenApiView,
    NotificationPreferencesApiView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationCenterView.as_view(), name="center"),
    path("devices/", NotificationDevicesView.as_view(), name="devices"),
    path("devices/link-code/", NotificationDeviceLinkCodeCreateView.as_view(), name="device_link_code"),
    path("devices/<int:pk>/revoke/", NotificationDeviceRevokeView.as_view(), name="device_revoke"),
    path("api/feed/", NotificationFeedApiView.as_view(), name="api_feed"),
    path("api/mark-seen/", NotificationMarkSeenApiView.as_view(), name="api_mark_seen"),
    path("api/mark-read/", NotificationMarkReadApiView.as_view(), name="api_mark_read"),
    path("api/dismiss/", NotificationDismissApiView.as_view(), name="api_dismiss"),
    path("api/browser-client/", NotificationBrowserClientApiView.as_view(), name="api_browser_client"),
    path("api/preferences/", NotificationPreferencesApiView.as_view(), name="api_preferences"),
    path("api/devices/exchange-code/", NotificationDeviceExchangeCodeApiView.as_view(), name="api_device_exchange_code"),
    path("api/devices/feed/", NotificationDeviceFeedApiView.as_view(), name="api_device_feed"),
    path("api/devices/ack/", NotificationDeviceAckApiView.as_view(), name="api_device_ack"),
    path("api/devices/revoke/", NotificationDeviceRevokeApiView.as_view(), name="api_device_revoke"),
]
