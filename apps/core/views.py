from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.db.models import Count, Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.workorders.policies import (
    can_manage_departments,
    can_manage_inventory,
)
from .forms import DepartmentForm
from .models import Department
from apps.workorders.models import WorkOrder, WorkOrderStatus
from apps.inventory.selectors import visible_devices_queryset
from apps.workorders.selectors import (
    resolve_active_actor,
    visible_departments_queryset,
    visible_workorders_queryset,
)
from apps.accounts.access_contracts import can_edit_role_definitions


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        visible_devices = visible_devices_queryset(self.request.user)
        visible_workorders = visible_workorders_queryset(self.request.user)
        context["device_count"] = visible_devices.count()
        context["open_workorder_count"] = visible_workorders.exclude(
            status__in=[WorkOrderStatus.CLOSED, WorkOrderStatus.CANCELLED]
        ).count()
        context["status_counts"] = [
            {"label": label, "value": visible_workorders.filter(status=status).count()}
            for status, label in WorkOrderStatus.choices
        ]
        context["recent_workorders"] = (
            visible_workorders.select_related("device", "author", "assignee", "department")
            .order_by("-created_at")[:8]
        )
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        context["can_manage_inventory"] = actor is not None and can_manage_inventory(actor)
        return context


class DepartmentManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_manage_departments(actor)


class DepartmentListView(DepartmentManagementMixin, ListView):
    model = Department
    template_name = "core/department_list.html"
    context_object_name = "departments"

    def get_queryset(self):
        visible_devices = visible_devices_queryset(self.request.user)
        visible_workorders = visible_workorders_queryset(self.request.user)
        return (
            visible_departments_queryset(self.request.user)
            .select_related("parent")
            .annotate(
                device_count=Count(
                    "medical_devices",
                    filter=Q(medical_devices__in=visible_devices),
                    distinct=True,
                ),
                workorder_count=Count(
                    "workorders",
                    filter=Q(workorders__in=visible_workorders),
                    distinct=True,
                ),
            )
            .order_by("parent_id", "name", "id")
        )


class DepartmentCreateView(DepartmentManagementMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = "core/department_form.html"
    success_url = reverse_lazy("core:department_list")

    def form_valid(self, form):
        messages.success(self.request, "Подразделение создано.")
        return super().form_valid(form)


class DepartmentUpdateView(DepartmentManagementMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = "core/department_form.html"
    success_url = reverse_lazy("core:department_list")

    def form_valid(self, form):
        messages.success(self.request, "Подразделение обновлено.")
        return super().form_valid(form)


class LegacyRoleRulesRedirectView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Закрытый совместимый адрес удалённого массового редактора ролей."""

    def test_func(self):
        return can_edit_role_definitions(self.request.user)

    def get(self, request, *args, **kwargs):
        return redirect("settings_center:role_catalog")

    def post(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["GET"])
