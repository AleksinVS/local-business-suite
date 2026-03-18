from django.urls import path

from .views import DashboardView, DepartmentCreateView, DepartmentListView, DepartmentUpdateView, RoleRulesUpdateView

app_name = "core"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("departments/", DepartmentListView.as_view(), name="department_list"),
    path("departments/new/", DepartmentCreateView.as_view(), name="department_create"),
    path("departments/<int:pk>/edit/", DepartmentUpdateView.as_view(), name="department_edit"),
    path("settings/roles/", RoleRulesUpdateView.as_view(), name="role_rules"),
]
