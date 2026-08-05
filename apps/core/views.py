import copy

from django.contrib import messages
from django.contrib.auth import get_user_model
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
    capability_definitions,
)
from .forms import DepartmentForm
from .models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import WorkOrder, WorkOrderStatus


CONFIRMATION_CAPABILITY_RISKS = {"critical"}
FALLBACK_CAPABILITY_SECTION = "Другие права"
SECTION_LABELS = {
    "workorders": "Работа с заявками",
    "organization": "Организация и настройки",
    "ai_memory": "ИИ и память организации",
    "waiting_list": "Лист ожидания",
    "personal_data": "Персональные данные",
}
FALLBACK_NON_FLAG_CAPABILITIES = (
    ("view_scope", "Просмотр заявок", "scope"),
    ("edit_scope", "Изменение заявок", "scope"),
    ("comment_scope", "Комментарии к заявкам", "scope"),
    ("upload_attachment_scope", "Загрузка файлов", "scope"),
    ("confirm_closure_scope", "Подтверждение закрытия", "scope"),
    ("rate_scope", "Оценка выполненной работы", "scope"),
    ("transition_scope", "Смена статусов заявок", "scope"),
    ("transition_targets", "Доступные статусы", "targets"),
)


def _role_capability_definitions(role_rules):
    """Готовит метаданные редактора из текущего серверного контракта.

    Рабочая копия может ещё не содержать новых ``section`` и ``risk``. В таком
    случае форма остаётся доступной, а право считается критическим до появления
    серверных метаданных. Это безопасный режим совместимости: риск не
    придумывается в браузере.
    """
    metadata = role_rules.get("$capabilities")
    if isinstance(metadata, dict):
        definitions = []
        for name, entry in metadata.items():
            if not isinstance(entry, dict):
                continue
            capability_type = entry.get("type")
            if capability_type not in {"flag", "scope", "targets"}:
                continue
            risk = entry.get("risk", "critical")
            section = entry.get("section")
            if isinstance(section, str) and section.strip():
                section = SECTION_LABELS.get(section, section)
            else:
                section = FALLBACK_CAPABILITY_SECTION
            definitions.append(
                {
                    "name": name,
                    "label": entry.get("label", name),
                    "description": entry.get("description", ""),
                    "type": capability_type,
                    "section": section,
                    "risk": risk if isinstance(risk, str) else "critical",
                }
            )
        if definitions:
            return definitions

    fallback_flags = [
        {
            "name": name,
            "label": label,
            "description": description,
            "type": capability_type,
            "section": FALLBACK_CAPABILITY_SECTION,
            "risk": "critical",
        }
        for name, label, description, capability_type in capability_definitions()
    ]
    fallback_non_flags = [
        {
            "name": name,
            "label": label,
            "description": "",
            "type": capability_type,
            "section": FALLBACK_CAPABILITY_SECTION,
            "risk": "critical",
        }
        for name, label, capability_type in FALLBACK_NON_FLAG_CAPABILITIES
    ]
    return fallback_non_flags + fallback_flags


def _requires_sensitive_confirmation(capability):
    return capability["risk"].lower() in CONFIRMATION_CAPABILITY_RISKS


def _parse_transition_targets(value):
    value = value.strip()
    if value == "*":
        return "*"
    return [item.strip() for item in value.split(",") if item.strip()]


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
        definitions = _role_capability_definitions(role_rules)
        sections_by_name = {}
        for definition in definitions:
            sections_by_name.setdefault(definition["section"], []).append(definition)

        # Служебные ключи ("$schema", справочник "$capabilities") — не роли:
        # в карточки редактора попадают только настоящие роли.
        role_rules_by_name = {
            role: rules
            for role, rules in role_rules.items()
            if not role.startswith("$") and isinstance(rules, dict)
        }
        user_model = get_user_model()
        role_member_ids = {role_name: set() for role_name in role_rules_by_name}
        # Один запрос вместо пары запросов на каждую роль: карточки и
        # предпросмотр используют один и тот же список уникальных сотрудников.
        for role_name, user_id in user_model.objects.filter(
            groups__name__in=role_rules_by_name
        ).values_list("groups__name", "id"):
            role_member_ids[role_name].add(user_id)
        role_member_ids = {
            role_name: sorted(member_ids) for role_name, member_ids in role_member_ids.items()
        }
        context["role_cards"] = [
            {
                "name": role_name,
                "display_name": rules.get("display_name", role_name),
                "description": rules.get("description", ""),
                "member_count": len(role_member_ids[role_name]),
                "sections": [
                    {
                        "name": section_name,
                        "capabilities": [
                            {
                                **definition,
                                "value": rules.get(definition["name"]),
                                "targets_value": (
                                    rules.get(definition["name"])
                                    if rules.get(definition["name"]) == "*"
                                    else ", ".join(rules.get(definition["name"], []))
                                )
                                if definition["type"] == "targets"
                                else "",
                                "requires_confirmation": _requires_sensitive_confirmation(definition),
                            }
                            for definition in section_definitions
                        ],
                    }
                    for section_name, section_definitions in sections_by_name.items()
                ],
            }
            for role_name, rules in role_rules_by_name.items()
        ]
        context["role_member_ids"] = role_member_ids
        context["capability_descriptions"] = definitions
        # Хеш отрисованной версии уходит в форму hidden-полем: защита от
        # потерянного обновления «два администратора открыли форму, второй
        # сохранил позже» — запись со старым хешом будет отклонена.
        context["role_rules_base_hash"] = normalized_hash(role_rules)

        context["scope_choices"] = [
            ("all", "Все заявки"),
            ("department_branch", "Ветка своего подразделения"),
            ("assigned_or_unassigned_or_authored", "Свои + Неназначенные"),
            ("assigned_or_unassigned", "Назначенные мне и неназначенные"),
            ("assigned", "Только назначенные мне"),
            ("visible", "Все доступные для просмотра"),
            ("authored", "Только свои"),
            ("none", "Нет доступа"),
        ]
        from apps.settings_center.models import SettingsChange

        context["role_change_history"] = SettingsChange.objects.filter(
            setting_id="core.contract.role_rules"
        ).select_related("actor")[:8]
        return context

    def post(self, request, *args, **kwargs):
        import json

        from apps.settings_center.contract_services import apply_contract_payload

        current_rules = get_contract("role_rules", request=request)
        original_rules = copy.deepcopy(current_rules)
        definitions = _role_capability_definitions(current_rules)
        # Хеш версии, которую пользователь видел при открытии формы (hidden-поле
        # из get_context_data). Если файл с тех пор изменился — запись отклонит
        # оптимистическая проверка. Поле обязательно и не даёт старому прямому
        # POST обойти проверку конкурирующей правки.
        base_hash = request.POST.get("base_hash")
        if not base_hash:
            messages.error(request, "Нельзя сохранить форму без версии контракта. Перезагрузите страницу.")
            return redirect("core:role_rules")

        # Обновляем только поля карточного редактора; служебные ключи
        # ("$schema", "$capabilities") и прочие поля ролей сохраняются как есть.
        for role_name, rules in current_rules.items():
            if role_name.startswith("$") or not isinstance(rules, dict):
                continue
            for definition in definitions:
                field_name = f"role_{role_name}_{definition['name']}"
                if definition["type"] == "flag":
                    rules[definition["name"]] = request.POST.get(field_name) == "on"
                elif definition["type"] == "scope" and request.POST.get(field_name):
                    rules[definition["name"]] = request.POST[field_name]
                elif definition["type"] == "targets" and field_name in request.POST:
                    rules[definition["name"]] = _parse_transition_targets(request.POST[field_name])

        # Описания прав — часть того же контракта, что и сами права. Поле
        # обновляем только если оно пришло в запросе: это сохраняет
        # совместимость с уже открытыми вкладками и внешними клиентами.
        capability_metadata = current_rules.get("$capabilities")
        if isinstance(capability_metadata, dict):
            for capability_name, metadata in capability_metadata.items():
                field_name = f"capability_{capability_name}_description"
                if isinstance(metadata, dict) and field_name in request.POST:
                    metadata["description"] = request.POST[field_name].strip()

        sensitive_changes = []
        for role_name, rules in current_rules.items():
            if role_name.startswith("$") or not isinstance(rules, dict):
                continue
            original_role_rules = original_rules.get(role_name, {})
            for definition in definitions:
                if not _requires_sensitive_confirmation(definition):
                    continue
                capability_name = definition["name"]
                if original_role_rules.get(capability_name) != rules.get(capability_name):
                    sensitive_changes.append(f"{role_name}: {definition['label']}")

        sensitive_confirmed = request.POST.get("confirm_sensitive_changes") == "yes"
        if sensitive_changes and not sensitive_confirmed:
            messages.error(
                request,
                "Изменение чувствительных прав требует явного подтверждения: "
                + "; ".join(sensitive_changes),
            )
            return redirect("core:role_rules")

        # Предпросмотр никогда не записывает рабочий контракт. Основной
        # интерфейс строит diff в браузере, а этот путь защищает прямые POST.
        if request.POST.get("action") == "preview":
            messages.info(request, "Предпросмотр подготовлен. Контракт ролей не изменён.")
            return redirect("core:role_rules")

        # Единственный путь записи: валидация + атомарная запись + SettingsChange.
        try:
            apply_contract_payload(
                actor=request.user,
                setting_id="core.contract.role_rules",
                raw_payload=json.dumps(current_rules, ensure_ascii=False),
                confirmed=not sensitive_changes or sensitive_confirmed,
                base_hash=base_hash,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("core:role_rules")

        messages.success(request, "Права ролей успешно обновлены.")
        return redirect("core:role_rules")
