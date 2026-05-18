from django.conf import settings
from django.urls import path

from .debug_views import debug_request
from .health_views import health_check, health_details
from .views import (
    DashboardView,
    DepartmentCreateView,
    DepartmentListView,
    DepartmentUpdateView,
    RoleRulesUpdateView,
)

app_name = "core"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("health/", health_check, name="health_check"),
    path("health/details/", health_details, name="health_details"),
    path("departments/", DepartmentListView.as_view(), name="department_list"),
    path("departments/new/", DepartmentCreateView.as_view(), name="department_create"),
    path(
        "departments/<int:pk>/edit/",
        DepartmentUpdateView.as_view(),
        name="department_edit",
    ),
    path("settings/roles/", RoleRulesUpdateView.as_view(), name="role_rules"),
]

if settings.DEBUG:
    urlpatterns.append(path("debug-request/", debug_request, name="debug_request"))
