from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

admin.site.site_header = settings.APP_DISPLAY_NAME
admin.site.site_title = settings.APP_DISPLAY_NAME
admin.site.index_title = settings.APP_DISPLAY_NAME

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("ai/", include("apps.ai.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("workorders/", include("apps.workorders.urls")),
    path("waiting-list/", include("apps.waiting_list.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
