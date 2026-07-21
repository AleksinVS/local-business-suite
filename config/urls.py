from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path

from apps.accounts.views import PortalLoginView, PortalLogoutView
from apps.core.media import serve_protected_media
from apps.notifications.views import service_worker

from . import views as config_views

admin.site.site_header = settings.APP_DISPLAY_NAME
admin.site.site_title = settings.APP_DISPLAY_NAME
admin.site.index_title = settings.APP_DISPLAY_NAME

handler400 = config_views.handler400
handler403 = config_views.handler403
handler404 = config_views.handler404
handler500 = config_views.handler500

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", PortalLoginView.as_view(), name="login"),
    path("accounts/logout/", PortalLogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("ai/", include("apps.ai.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("memory/", include("apps.memory.urls")),
    path("memory/", include("apps.filehub.urls")),
    path("settings/", include("apps.settings_center.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("service-worker.js", service_worker, name="service_worker"),
    path("workorders/", include("apps.workorders.urls")),
    path("waiting-list/", include("apps.waiting_list.urls")),
    # Медиа раздаётся только через авторизованный dispatcher (login_required +
    # доменная политика доступа по префиксу первого сегмента пути) в любом
    # окружении. Раньше здесь стоял static(MEDIA_URL, ...), который в dev отдавал
    # файлы без проверки прав, а при DEBUG=0 отключался. Единый маршрут
    # /media/<prefix>/<path> совпадает с file.url и разбирается по политикам,
    # которые приложения регистрируют в apps.core.media.
    re_path(
        r"^media/(?P<path>.*)$",
        login_required(serve_protected_media),
        name="workorder_attachment",
    ),
]
