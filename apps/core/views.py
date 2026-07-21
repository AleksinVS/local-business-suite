from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.db.models import Count
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.core.contract_store import get_contract, normalized_hash
from apps.workorders.policies import (
    can_manage_departments,
    can_manage_inventory,
    can_manage_roles,
)
from .forms import DepartmentForm
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
        return can_manage_departments(self.request.user)


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


class RoleRulesUpdateView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "core/role_rules_form.html"

    def test_func(self):
        return can_manage_roles(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role_rules = get_contract("role_rules", request=self.request)
        context["role_rules"] = role_rules
        # Хеш отрисованной версии уходит в форму hidden-полем: защита от
        # потерянного обновления «два администратора открыли форму, второй
        # сохранил позже» — запись со старым хешом будет отклонена.
        context["role_rules_base_hash"] = normalized_hash(role_rules)

        # Define common boolean flags for UI
        context["available_flags"] = [
            ("create_workorder", "Создание заявок"),
            ("manage_inventory", "Управление инвентарем"),
            ("manage_board_columns", "Управление досками"),
            ("manage_assignments", "Управление назначениями"),
            ("view_analytics", "Просмотр аналитики"),
            ("manage_departments", "Управление подразделениями"),
            ("manage_roles", "Управление ролями"),
        ]
        context["view_scopes"] = [
            ("all", "Все заявки"),
            ("department_branch", "Ветка своего подразделения"),
            ("assigned_or_unassigned_or_authored", "Свои + Неназначенные"),
            ("authored", "Только свои"),
            ("none", "Нет доступа"),
        ]
        return context

    def post(self, request, *args, **kwargs):
        import json

        from apps.settings_center.contract_services import apply_contract_payload

        current_rules = get_contract("role_rules", request=request)
        # Хеш версии, которую пользователь видел при открытии формы (hidden-поле
        # из get_context_data). Если файл с тех пор изменился — запись отклонит
        # оптимистическая проверка. Отсутствие поля (прямые POST старых клиентов)
        # означает запись без проверки — обратная совместимость.
        base_hash = request.POST.get("base_hash") or None

        # Обновляем только поля, которыми управляет упрощённый UI; остальные поля
        # ролей (в т.ч. $schema) сохраняются как есть.
        for role_name, rules in current_rules.items():
            if not isinstance(rules, dict):
                continue
            for flag, _ in [
                ("create_workorder", "Создание заявок"),
                ("manage_inventory", "Управление инвентарем"),
                ("manage_board_columns", "Управление досками"),
                ("manage_assignments", "Управление назначениями"),
                ("view_analytics", "Просмотр аналитики"),
                ("manage_departments", "Управление подразделениями"),
                ("manage_roles", "Управление ролями"),
            ]:
                rules[flag] = request.POST.get(f"role_{role_name}_{flag}") == "on"

            view_scope = request.POST.get(f"role_{role_name}_view_scope")
            if view_scope:
                rules["view_scope"] = view_scope

        # Единственный путь записи: валидация + атомарная запись + SettingsChange.
        try:
            apply_contract_payload(
                actor=request.user,
                setting_id="core.contract.role_rules",
                raw_payload=json.dumps(current_rules, ensure_ascii=False),
                confirmed=True,
                base_hash=base_hash,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("core:role_rules")

        messages.success(request, "Права ролей успешно обновлены.")
        return redirect("core:role_rules")
