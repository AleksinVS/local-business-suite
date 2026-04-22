from django.urls import re_path

from .health_views import health_check
from .views import (
    DashboardView,
    DepartmentCreateView,
    DepartmentListView,
    DepartmentUpdateView,
    RoleRulesUpdateView,
)

app_name = "core"

urlpatterns = [
    re_path(r"^/?$", DashboardView.as_view(), name="dashboard"),
    re_path(r"^health/?$", health_check, name="health_check"),
    re_path(r"^departments/?$", DepartmentListView.as_view(), name="department_list"),
    re_path(
        r"^departments/new/?$", DepartmentCreateView.as_view(), name="department_create"
    ),
    re_path(
        r"^departments/(?P<pk>\d+)/edit/?$",
        DepartmentUpdateView.as_view(),
        name="department_edit",
    ),
    re_path(r"^settings/roles/?$", RoleRulesUpdateView.as_view(), name="role_rules"),
]
