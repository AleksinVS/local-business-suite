from django.urls import re_path

from .views import AnalyticsDashboardView

app_name = "analytics"

urlpatterns = [
    re_path(r"^/?$", AnalyticsDashboardView.as_view(), name="dashboard"),
]
