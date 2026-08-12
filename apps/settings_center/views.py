from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.accounts.models import AccessAssignmentAudit, ExternalIdentity
from apps.accounts.access_contracts import (
    apply_role_definition_change,
    preview_role_definition_change,
    role_catalog_rows,
    role_definition_read_model,
)
from apps.accounts.selectors import (
    effective_access_for_user,
    split_user_groups,
    user_access_overview,
)
from apps.accounts.services import (
    apply_role_assignment,
    create_local_user,
    disable_local_user,
    external_identity_audit_snapshot,
    link_ad_identity,
    preview_role_assignment,
    update_local_user,
    user_profile_audit_snapshot,
)
from apps.core.contract_store import normalized_hash
from apps.core.json_utils import pretty_json
from apps.workorders.forms import BoardAccessForm
from apps.workorders.models import Board, BoardAccessAudit
from apps.workorders.policies import board_access_role_names, can_manage_board_access, can_manage_roles
from apps.workorders.services import apply_board_access, preview_board_access

from .contract_services import apply_contract_payload, preview_contract_payload, read_contract_value
from .env_services import create_env_proposal, env_status_rows
from .forms import (
    ContractPayloadForm,
    EnvProposalForm,
    ExternalIdentityForm,
    HelpQuestionForm,
    MemoryGroupMembershipForm,
    PortalUserCreateForm,
    PortalUserProfileUpdateForm,
    PortalUserUpdateForm,
    RoleDefinitionForm,
)
from .help_services import answer_help_question, initial_help_text
from .models import SettingsChange
from .policies import can_manage_settings
from .registry import get_registry
from .services import record_settings_change


class SettingsManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_settings(self.request.user)


class UserManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_roles(self.request.user)


class SuperuserUserManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return bool(
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.is_superuser
        )


class BoardAccessManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_board_access(self.request.user)


class RoleDefinitionManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return bool(
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.is_superuser
        )


class SettingsDashboardView(SettingsManagementMixin, TemplateView):
    template_name = "settings_center/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["domains"] = get_registry().by_domain()
        context["recent_changes"] = SettingsChange.objects.select_related("actor")[:12]
        context["can_manage_roles"] = can_manage_roles(self.request.user)
        context["can_manage_board_access"] = can_manage_board_access(self.request.user)
        return context


class BoardAccessListView(BoardAccessManagementMixin, ListView):
    model = Board
    template_name = "settings_center/board_access_list.html"
    context_object_name = "boards"

    def get_queryset(self):
        return Board.objects.prefetch_related("allowed_groups").order_by("title")


class BoardAccessView(BoardAccessManagementMixin, TemplateView):
    template_name = "settings_center/board_access_form.html"

    def get(self, request, *args, **kwargs):
        self.board = get_object_or_404(Board, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or BoardAccessForm(
            initial={
                "group_names": list(
                    self.board.allowed_groups.order_by("name").values_list("name", flat=True)
                )
            }
        )
        context.update(
            {
                "board": self.board,
                "form": form,
                "preview": kwargs.get("preview"),
                "history": self.board.access_audits.select_related("actor")[:8],
                "return_url": reverse("settings_center:board_access_list"),
                "is_break_glass": False,
                "legacy_group_names": sorted(
                    set(self.board.allowed_groups.values_list("name", flat=True))
                    - set(board_access_role_names())
                ),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        self.board = get_object_or_404(Board, pk=kwargs["pk"])
        form = BoardAccessForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        selected = form.cleaned_data["group_names"]
        reason = form.cleaned_data["reason"]
        try:
            if request.POST.get("action") == "preview":
                preview = preview_board_access(
                    actor=request.user,
                    board=self.board,
                    selected_group_names=selected,
                    reason=reason,
                )
                preview_form = BoardAccessForm(
                    initial={
                        "group_names": selected,
                        "reason": reason,
                        "preview_token": preview["preview_token"],
                    }
                )
                return self.render_to_response(
                    self.get_context_data(form=preview_form, preview=preview)
                )
            board, audit = apply_board_access(
                actor=request.user,
                board=self.board,
                selected_group_names=selected,
                preview_token=form.cleaned_data["preview_token"],
                risk_confirmed=form.cleaned_data["risk_confirmed"],
                reason=reason,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(request, f"Доступ к доске «{board.title}» изменён. Аудит #{audit.pk}.")
        return redirect("settings_center:board_access", pk=board.pk)


class RoleCatalogView(RoleDefinitionManagementMixin, TemplateView):
    template_name = "settings_center/role_catalog.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["roles"] = role_catalog_rows()
        return context


class RoleDefinitionView(RoleDefinitionManagementMixin, TemplateView):
    template_name = "settings_center/role_definition_form.html"

    def _load_role(self, kwargs):
        self.role_code = kwargs["role_code"]
        try:
            self.role_read_model = role_definition_read_model(self.role_code)
        except ValidationError as exc:
            raise Http404("Роль не найдена.") from exc

    def get(self, request, *args, **kwargs):
        self._load_role(kwargs)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or RoleDefinitionForm(
            role_read_model=self.role_read_model,
            initial={"base_hash": self.role_read_model["base_hash"]},
        )
        context.update(
            {
                "role": self.role_read_model,
                "form": form,
                "preview": kwargs.get("preview"),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        self._load_role(kwargs)
        form = RoleDefinitionForm(request.POST, role_read_model=self.role_read_model)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        proposed = form.proposed_config()
        try:
            if request.POST.get("action") == "preview":
                preview = preview_role_definition_change(
                    actor=request.user,
                    role_code=self.role_code,
                    proposed_config=proposed,
                    base_hash=form.cleaned_data["base_hash"],
                )
                preview_form = RoleDefinitionForm(
                    role_read_model=self.role_read_model,
                    initial={
                        "base_hash": preview["base_hash"],
                        "preview_token": preview["preview_token"],
                        **{
                            f"capability__{code}": (["*"] if value == "*" else value)
                            for code, value in preview["proposed_config"].items()
                        },
                    },
                )
                return self.render_to_response(
                    self.get_context_data(form=preview_form, preview=preview)
                )
            change = apply_role_definition_change(
                actor=request.user,
                role_code=self.role_code,
                proposed_config=proposed,
                base_hash=form.cleaned_data["base_hash"],
                preview_token=form.cleaned_data["preview_token"],
                risk_confirmed=form.cleaned_data["risk_confirmed"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(request, f"Роль «{self.role_read_model['label']}» изменена. Аудит #{change.pk}.")
        return redirect("settings_center:role_definition", role_code=self.role_code)


class SettingDetailView(SettingsManagementMixin, FormView):
    template_name = "settings_center/setting_detail.html"
    form_class = ContractPayloadForm

    def dispatch(self, request, *args, **kwargs):
        self.descriptor = get_registry().get(kwargs["setting_id"])
        if self.descriptor.setting_id == "core.contract.role_rules":
            return redirect("settings_center:role_catalog")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.descriptor.storage_kind == "runtime_contract":
            try:
                payload = read_contract_value(self.descriptor)
                initial["payload"] = pretty_json(payload)
                initial["base_hash"] = normalized_hash(payload)
            except Exception as exc:
                initial["payload"] = f'{{"error": "{exc}"}}'
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["descriptor"] = self.descriptor
        context["is_contract"] = self.descriptor.storage_kind == "runtime_contract"
        context["can_edit"] = self.descriptor.is_editable
        context["is_workflow_transition_matrix"] = self.descriptor.widget == "workflow_transition_matrix"
        context["is_status_color_palette"] = self.descriptor.widget == "status_color_palette"
        return context

    def form_valid(self, form):
        if self.descriptor.storage_kind != "runtime_contract":
            messages.error(self.request, "Эта настройка не редактируется как JSON-контракт.")
            return self.form_invalid(form)
        try:
            if self.request.POST.get("action") == "preview":
                preview = preview_contract_payload(
                    descriptor=self.descriptor,
                    raw_payload=form.cleaned_data["payload"],
                )
                record_settings_change(
                    actor=self.request.user,
                    descriptor=self.descriptor,
                    action=SettingsChange.Action.PREVIEW,
                    status=SettingsChange.Status.PENDING,
                    before=preview["before"],
                    after=preview["after"],
                    validation_result=preview["validation_result"],
                )
                return self.render_to_response(
                    self.get_context_data(
                        form=form,
                        preview=preview,
                    )
                )
            change = apply_contract_payload(
                actor=self.request.user,
                setting_id=self.descriptor.setting_id,
                raw_payload=form.cleaned_data["payload"],
                confirmed=form.cleaned_data["confirm"],
                base_hash=form.cleaned_data["base_hash"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, f"Настройка применена. Аудит #{change.pk}.")
        return redirect("settings_center:setting_detail", setting_id=self.descriptor.setting_id)


class WorkflowTransitionMatrixView(SettingsManagementMixin, TemplateView):
    template_name = "settings_center/workflow_transitions.html"
    setting_id = "core.contract.workflow_rules"

    def get_descriptor(self):
        return get_registry().get(self.setting_id)

    def get_payload(self):
        return read_contract_value(self.get_descriptor())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        descriptor = self.get_descriptor()
        payload = self.get_payload()
        statuses = payload.get("statuses", [])
        transitions = payload.get("transitions", {})
        rows = []
        allowed_count = 0
        possible_count = 0
        for source in statuses:
            cells = []
            enabled_targets = set(transitions.get(source, []))
            for target in statuses:
                is_self = source == target
                enabled = target in enabled_targets
                if not is_self:
                    possible_count += 1
                    if enabled:
                        allowed_count += 1
                cells.append(
                    {
                        "target": target,
                        "enabled": enabled,
                        "is_self": is_self,
                        "field_name": f"transition__{source}__{target}",
                    }
                )
            rows.append({"source": source, "cells": cells})
        context.update(
            {
                "descriptor": descriptor,
                "statuses": statuses,
                "rows": rows,
                "allowed_count": allowed_count,
                "possible_count": possible_count,
                "raw_payload": pretty_json(payload),
                "base_hash": normalized_hash(payload),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        descriptor = self.get_descriptor()
        before = self.get_payload()
        statuses = before.get("statuses", [])
        action = request.POST.get("action", "apply_matrix")
        after = {
            "statuses": statuses,
            "transitions": self._build_transitions(
                statuses=statuses,
                post=request.POST,
                mode=action,
            ),
        }
        try:
            change = apply_contract_payload(
                actor=request.user,
                setting_id=descriptor.setting_id,
                raw_payload=json.dumps(after, ensure_ascii=False),
                confirmed=request.POST.get("confirm") == "on",
                base_hash=request.POST.get("base_hash"),
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
            return self.render_to_response(self.get_context_data())
        messages.success(request, f"Переходы сохранены. Аудит #{change.pk}.")
        return redirect("settings_center:workflow_transitions")

    @staticmethod
    def _build_transitions(*, statuses, post, mode):
        transitions = {}
        for source in statuses:
            if mode == "allow_all":
                transitions[source] = [target for target in statuses if target != source]
            elif mode == "deny_all":
                transitions[source] = []
            else:
                transitions[source] = [
                    target
                    for target in statuses
                    if target != source and post.get(f"transition__{source}__{target}") == "on"
                ]
        return transitions


class WorkOrderStatusColorSettingsView(SettingsManagementMixin, TemplateView):
    template_name = "settings_center/workorder_status_colors.html"
    setting_id = "workorders.contract.status_colors"

    def get_descriptor(self):
        return get_registry().get(self.setting_id)

    def get_payload(self):
        return read_contract_value(self.get_descriptor())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        descriptor = self.get_descriptor()
        payload = self.get_payload()
        rows = [
            {
                "code": code,
                "label": config.get("label", code),
                "color": config.get("color", "#64748b"),
                "background": config.get("background", "#f8fafc"),
            }
            for code, config in payload.get("statuses", {}).items()
        ]
        context.update(
            {
                "descriptor": descriptor,
                "rows": rows,
                "raw_payload": pretty_json(payload),
                "base_hash": normalized_hash(payload),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        descriptor = self.get_descriptor()
        before = self.get_payload()
        statuses = {}
        for code, config in before.get("statuses", {}).items():
            statuses[code] = {
                "label": config.get("label", code),
                "color": request.POST.get(f"color__{code}", config.get("color", "#64748b")),
                "background": request.POST.get(
                    f"background__{code}",
                    config.get("background", "#f8fafc"),
                ),
            }
        after = {
            "$schema": before.get("$schema", "./schemas/workorder_status_colors.schema.json"),
            "statuses": statuses,
        }
        try:
            change = apply_contract_payload(
                actor=request.user,
                setting_id=descriptor.setting_id,
                raw_payload=json.dumps(after, ensure_ascii=False),
                confirmed=request.POST.get("confirm") == "on",
                base_hash=request.POST.get("base_hash"),
            )
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
            return self.render_to_response(self.get_context_data())
        messages.success(request, f"Цвета статусов сохранены. Аудит #{change.pk}.")
        return redirect("settings_center:workorder_status_colors")


class EnvStatusView(SettingsManagementMixin, TemplateView):
    template_name = "settings_center/env_status.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["rows"] = env_status_rows()
        return context


class EnvProposalView(SettingsManagementMixin, FormView):
    template_name = "settings_center/env_proposal.html"
    form_class = EnvProposalForm
    success_url = reverse_lazy("settings_center:env_status")

    def form_valid(self, form):
        try:
            proposal = create_env_proposal(
                actor=self.request.user,
                target_label=form.cleaned_data["target_label"],
                changes={form.cleaned_data["key"]: form.cleaned_data["value"]},
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, f"Заявка на изменение .env создана: {proposal.file_path}")
        return super().form_valid(form)


class HelpPanelView(SettingsManagementMixin, View):
    def get(self, request, setting_id):
        descriptor = get_registry().get(setting_id)
        return render(
            request,
            "settings_center/partials/help_panel.html",
            {
                "descriptor": descriptor,
                "initial_help": initial_help_text(setting_id),
                "form": HelpQuestionForm(),
            },
        )


class HelpAskView(SettingsManagementMixin, View):
    def post(self, request, setting_id):
        form = HelpQuestionForm(request.POST)
        descriptor = get_registry().get(setting_id)
        answer = None
        if form.is_valid():
            answer = answer_help_question(
                setting_id=setting_id,
                question=form.cleaned_data["question"],
            )
        return render(
            request,
            "settings_center/partials/help_answer.html",
            {"descriptor": descriptor, "answer": answer, "form": form},
        )


class UserListView(UserManagementMixin, ListView):
    model = get_user_model()
    template_name = "settings_center/user_list.html"
    context_object_name = "portal_users"
    paginate_by = 50

    def get_queryset(self):
        from .access_filters import filter_user_queryset

        queryset = self.model.objects.select_related("department__parent").prefetch_related(
            "groups__profile", "external_identities"
        ).order_by("username")
        queryset, self.access_filter_state = filter_user_queryset(queryset, self.request.GET)
        return queryset

    def get_context_data(self, **kwargs):
        from .access_filters import ATTENTION_VALUE, user_filter_options

        context = super().get_context_data(**kwargs)
        for portal_user in context["portal_users"]:
            role_groups, technical_groups = split_user_groups(portal_user)
            portal_user.access_overview = user_access_overview(portal_user)
            portal_user.access_overview["roles"] = [
                getattr(getattr(group, "profile", None), "title", "") or group.name
                for group in role_groups
            ]
            portal_user.access_overview["has_technical_groups"] = bool(technical_groups)
        filter_options = user_filter_options()
        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context.update(
            {
                "access_filter_state": self.access_filter_state,
                "attention_value": ATTENTION_VALUE,
                "role_filter_options": filter_options["roles"],
                "department_filter_options": filter_options["departments"],
                "pagination_query": query_params.urlencode(),
                "can_manage_board_access": can_manage_board_access(self.request.user),
            }
        )
        return context


class MemoryGroupMembershipView(SuperuserUserManagementMixin, TemplateView):
    template_name = "settings_center/memory_group_membership_form.html"

    def _load_target(self, kwargs):
        self.target_user = get_object_or_404(get_user_model(), pk=kwargs["pk"])

    def get(self, request, *args, **kwargs):
        self._load_target(kwargs)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.memory.models import MemoryGroupMembershipAudit
        from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES

        context = super().get_context_data(**kwargs)
        current = list(
            self.target_user.groups.filter(name__in=MEMORY_REVIEW_GROUP_CAPABILITIES)
            .order_by("name")
            .values_list("name", flat=True)
        )
        context.update(
            {
                "target_user": self.target_user,
                "form": kwargs.get("form")
                or MemoryGroupMembershipForm(initial={"group_names": current}),
                "preview": kwargs.get("preview"),
                "history": MemoryGroupMembershipAudit.objects.filter(
                    target_user=self.target_user
                ).select_related("actor")[:8],
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        from apps.memory.access_services import (
            apply_memory_group_membership,
            preview_memory_group_membership,
        )

        self._load_target(kwargs)
        form = MemoryGroupMembershipForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        selected = form.cleaned_data["group_names"]
        reason = form.cleaned_data["reason"]
        try:
            if request.POST.get("action") == "preview":
                preview = preview_memory_group_membership(
                    actor=request.user,
                    target_user=self.target_user,
                    selected_group_names=selected,
                    reason=reason,
                )
                preview_form = MemoryGroupMembershipForm(
                    initial={
                        "group_names": selected,
                        "reason": reason,
                        "preview_token": preview["preview_token"],
                    }
                )
                return self.render_to_response(
                    self.get_context_data(form=preview_form, preview=preview)
                )
            target, audit = apply_memory_group_membership(
                actor=request.user,
                target_user=self.target_user,
                selected_group_names=selected,
                reason=reason,
                preview_token=form.cleaned_data["preview_token"],
                confirmed=form.cleaned_data["confirmed"],
            )
        except (PermissionDenied, ValidationError) as exc:
            form.add_error(None, exc)
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(
            request,
            f"Технические полномочия памяти пользователя {target.username} изменены. "
            f"Аудит #{audit.pk}.",
        )
        return redirect("settings_center:memory_group_membership", pk=target.pk)


class UserCreateView(SuperuserUserManagementMixin, CreateView):
    model = get_user_model()
    form_class = PortalUserCreateForm
    template_name = "settings_center/user_form.html"

    def get_success_url(self):
        return f"{reverse('settings_center:user_edit', kwargs={'pk': self.object.pk})}?focus=assign#assign"

    def form_valid(self, form):
        descriptor = get_registry().get("accounts.users.local_management")

        def audit_callback(before, after):
            record_settings_change(
                actor=self.request.user,
                descriptor=descriptor,
                action=SettingsChange.Action.USER_CREATE,
                status=SettingsChange.Status.APPLIED,
                before=user_profile_audit_snapshot(before),
                after=user_profile_audit_snapshot(after),
                validation_result={"valid": True},
            )
        user = create_local_user(
            actor=self.request.user,
            cleaned_data=form.cleaned_data.copy(),
            audit_callback=audit_callback,
        )
        self.object = user
        messages.success(self.request, "Пользователь создан.")
        return HttpResponseRedirect(self.get_success_url())


class UserUpdateView(UserManagementMixin, FormView):
    form_class = PortalUserUpdateForm
    template_name = "settings_center/user_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not can_manage_roles(request.user):
            return super().dispatch(request, *args, **kwargs)
        self.portal_user = get_object_or_404(
            get_user_model().objects.select_related("department__parent"),
            pk=kwargs["pk"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["portal_user"] = self.portal_user
        kwargs["actor"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        _roles, technical_groups = split_user_groups(self.portal_user)
        context.update(
            {
                "portal_user": self.portal_user,
                "effective_access": effective_access_for_user(self.portal_user),
                "technical_groups": technical_groups,
                "access_audits": AccessAssignmentAudit.objects.filter(
                    target_user=self.portal_user
                ).select_related("actor")[:10],
            }
        )
        return context

    def form_valid(self, form):
        selected_role_names = [group.name for group in form.cleaned_data["roles"]]
        if self.request.POST.get("action") == "preview":
            try:
                preview = preview_role_assignment(
                    actor=self.request.user,
                    target_user=self.portal_user,
                    selected_role_names=selected_role_names,
                    is_staff=form.cleaned_data["is_staff"],
                    is_superuser=form.cleaned_data["is_superuser"],
                )
            except (PermissionDenied, ValidationError) as exc:
                form.add_error(None, exc)
                return self.form_invalid(form)
            mutable_data = form.data.copy()
            mutable_data["preview_token"] = preview["preview_token"]
            form.data = mutable_data
            return self.render_to_response(self.get_context_data(form=form, preview=preview))

        try:
            _user, audit = apply_role_assignment(
                actor=self.request.user,
                target_user=self.portal_user,
                selected_role_names=selected_role_names,
                preview_token=form.cleaned_data["preview_token"],
                risk_confirmed=form.cleaned_data["confirm_risk"],
                is_staff=form.cleaned_data["is_staff"],
                is_superuser=form.cleaned_data["is_superuser"],
            )
        except (PermissionDenied, ValidationError) as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, f"Доступ сохранён. Аудит #{audit.pk}.")
        return redirect("settings_center:user_edit", pk=self.portal_user.pk)


class UserProfileUpdateView(SuperuserUserManagementMixin, UpdateView):
    model = get_user_model()
    form_class = PortalUserProfileUpdateForm
    template_name = "settings_center/user_form.html"
    context_object_name = "profile_user"
    success_url = reverse_lazy("settings_center:user_list")

    def form_valid(self, form):
        password_changed = bool(form.cleaned_data.get("password"))
        changed_fields = sorted(set(form.changed_data) - {"password"})
        descriptor = get_registry().get("accounts.users.local_management")

        def audit_callback(before, after):
            record_settings_change(
                actor=self.request.user,
                descriptor=descriptor,
                action=SettingsChange.Action.USER_UPDATE,
                status=SettingsChange.Status.APPLIED,
                before=user_profile_audit_snapshot(before),
                after=user_profile_audit_snapshot(after),
                validation_result={
                    "valid": True,
                    "changed_fields": changed_fields,
                    "password_changed": password_changed,
                },
            )
        update_local_user(
            actor=self.request.user,
            user=self.object,
            cleaned_data=form.cleaned_data.copy(),
            audit_callback=audit_callback,
        )
        messages.success(self.request, "Учётная запись пользователя обновлена.")
        return HttpResponseRedirect(self.get_success_url())


class UserDisableView(SuperuserUserManagementMixin, View):
    def post(self, request, pk):
        User = get_user_model()
        user = get_object_or_404(User, pk=pk)
        try:
            descriptor = get_registry().get("accounts.users.local_management")

            def audit_callback(before, after):
                record_settings_change(
                    actor=request.user,
                    descriptor=descriptor,
                    action=SettingsChange.Action.USER_DISABLE,
                    status=SettingsChange.Status.APPLIED,
                    before=user_profile_audit_snapshot(before),
                    after=user_profile_audit_snapshot(after),
                    validation_result={"valid": True},
                )
            disable_local_user(
                actor=request.user,
                user=user,
                audit_callback=audit_callback,
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("settings_center:user_list")
        messages.success(request, "Пользователь отключен.")
        return redirect("settings_center:user_list")


class UserADLinkView(SuperuserUserManagementMixin, FormView):
    template_name = "settings_center/ad_link_form.html"
    form_class = ExternalIdentityForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        User = get_user_model()
        self.portal_user = get_object_or_404(User, pk=kwargs["pk"])
        self.identity = ExternalIdentity.objects.filter(user=self.portal_user).first()
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("settings_center:user_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.identity:
            kwargs["instance"] = self.identity
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["portal_user"] = self.portal_user
        return context

    def form_valid(self, form):
        changed_fields = sorted(form.changed_data)
        descriptor = get_registry().get("accounts.user.ad_identity_link")

        def audit_callback(before, after):
            record_settings_change(
                actor=self.request.user,
                descriptor=descriptor,
                action=SettingsChange.Action.AD_LINK,
                status=SettingsChange.Status.APPLIED,
                before=external_identity_audit_snapshot(before),
                after=external_identity_audit_snapshot(after),
                validation_result={"valid": True, "changed_fields": changed_fields},
            )
        link_ad_identity(
            actor=self.request.user,
            user=self.portal_user,
            cleaned_data=form.cleaned_data.copy(),
            audit_callback=audit_callback,
        )
        messages.success(self.request, "AD identity link сохранен.")
        return super().form_valid(form)
