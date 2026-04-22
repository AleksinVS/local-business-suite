from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

admin.site.site_header = settings.APP_DISPLAY_NAME
admin.site.site_title = settings.APP_DISPLAY_NAME
admin.site.index_title = settings.APP_DISPLAY_NAME

urlpatterns = [
    re_path(r"^admin/?", admin.site.urls),
    re_path(r"^accounts/login/?$", auth_views.LoginView.as_view(), name="login"),
    re_path(r"^accounts/logout/?$", auth_views.LogoutView.as_view(), name="logout"),
    re_path(r"^", include("apps.core.urls")),
    re_path(r"^ai/?", include("apps.ai.urls")),
    re_path(r"^analytics/?", include("apps.analytics.urls")),
    re_path(r"^inventory/?", include("apps.inventory.urls")),
    re_path(r"^workorders/?", include("apps.workorders.urls")),
    re_path(r"^waiting-list/?", include("apps.waiting_list.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
