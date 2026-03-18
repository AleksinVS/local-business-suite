from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.workorders.policies import can_manage_inventory
from .forms import DepartmentForm, RoleRulesForm
from .models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import WorkOrder, WorkOrderStatus


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["device_count"] = MedicalDevice.objects.count()
        context["open_workorder_count"] = WorkOrder.objects.exclude(
            status__in=[WorkOrderStatus.CLOSED, WorkOrderStatus.CANCELLED]
        ).count()
        context["status_counts"] = [
            {"label": label, "value": WorkOrder.objects.filter(status=status).count()}
            for status, label in WorkOrderStatus.choices
        ]
        context["recent_workorders"] = (
            WorkOrder.objects.select_related("device", "author", "assignee", "department")
            .order_by("-created_at")[:8]
        )
        context["can_manage_inventory"] = can_manage_inventory(self.request.user)
        return context


class DepartmentManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_inventory(self.request.user)


class DepartmentListView(DepartmentManagementMixin, ListView):
    model = Department
    template_name = "core/department_list.html"
    context_object_name = "departments"

    def get_queryset(self):
        return (
            Department.objects.select_related("parent")
            .annotate(device_count=Count("medical_devices"), workorder_count=Count("workorders"))
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


class RoleRulesUpdateView(DepartmentManagementMixin, FormView):
    template_name = "core/role_rules_form.html"
    form_class = RoleRulesForm
    success_url = reverse_lazy("core:role_rules")

    def form_valid(self, form):
        payload = form.cleaned_data["rules_payload"]
        settings.LOCAL_BUSINESS_ROLE_RULES_FILE.write_text(form.cleaned_data["rules_json"] + "\n", encoding="utf-8")
        settings.LOCAL_BUSINESS_ROLE_RULES = payload
        messages.success(self.request, "Конфигурация ролей обновлена.")
        return super().form_valid(form)
