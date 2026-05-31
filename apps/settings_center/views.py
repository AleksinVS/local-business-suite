from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.accounts.models import ExternalIdentity
from apps.accounts.services import create_local_user, disable_local_user, link_ad_identity, update_local_user
from apps.core.json_utils import pretty_json

from .contract_services import apply_contract_payload, preview_contract_payload, read_contract_value
from .env_services import create_env_proposal, env_status_rows
from .forms import (
    ContractPayloadForm,
    EnvProposalForm,
    ExternalIdentityForm,
    HelpQuestionForm,
    PortalUserCreateForm,
    PortalUserUpdateForm,
)
from .help_services import answer_help_question, initial_help_text
from .models import SettingsChange
from .policies import can_manage_settings, can_manage_users
from .registry import get_registry
from .services import record_settings_change


class SettingsManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_settings(self.request.user)


class UserManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_users(self.request.user)


class SettingsDashboardView(SettingsManagementMixin, TemplateView):
    template_name = "settings_center/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["domains"] = get_registry().by_domain()
        context["recent_changes"] = SettingsChange.objects.select_related("actor")[:12]
        return context


class SettingDetailView(SettingsManagementMixin, FormView):
    template_name = "settings_center/setting_detail.html"
    form_class = ContractPayloadForm

    def dispatch(self, request, *args, **kwargs):
        self.descriptor = get_registry().get(kwargs["setting_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.descriptor.storage_kind == "runtime_contract":
            try:
                initial["payload"] = pretty_json(read_contract_value(self.descriptor))
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
        return self.model.objects.select_related("department").prefetch_related("groups", "external_identities").order_by("username")


class UserCreateView(UserManagementMixin, CreateView):
    model = get_user_model()
    form_class = PortalUserCreateForm
    template_name = "settings_center/user_form.html"
    success_url = reverse_lazy("settings_center:user_list")

    def form_valid(self, form):
        user = create_local_user(actor=self.request.user, cleaned_data=form.cleaned_data.copy())
        self.object = user
        descriptor = get_registry().get("accounts.users.local_management")
        record_settings_change(
            actor=self.request.user,
            descriptor=descriptor,
            action=SettingsChange.Action.USER_CREATE,
            status=SettingsChange.Status.APPLIED,
            before={},
            after={"user_id": user.id, "username": user.username, "is_active": user.is_active},
            validation_result={"valid": True},
        )
        messages.success(self.request, "Пользователь создан.")
        return HttpResponseRedirect(self.get_success_url())


class UserUpdateView(UserManagementMixin, UpdateView):
    model = get_user_model()
    form_class = PortalUserUpdateForm
    template_name = "settings_center/user_form.html"
    success_url = reverse_lazy("settings_center:user_list")

    def form_valid(self, form):
        before = {
            "user_id": self.object.id,
            "username": self.object.username,
            "groups": list(self.object.groups.values_list("name", flat=True)),
            "is_staff": self.object.is_staff,
            "is_superuser": self.object.is_superuser,
            "is_active": self.object.is_active,
        }
        user = update_local_user(actor=self.request.user, user=self.object, cleaned_data=form.cleaned_data.copy())
        descriptor = get_registry().get("accounts.users.local_management")
        record_settings_change(
            actor=self.request.user,
            descriptor=descriptor,
            action=SettingsChange.Action.USER_UPDATE,
            status=SettingsChange.Status.APPLIED,
            before=before,
            after={
                "user_id": user.id,
                "username": user.username,
                "groups": list(user.groups.values_list("name", flat=True)),
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "is_active": user.is_active,
            },
            validation_result={"valid": True},
        )
        messages.success(self.request, "Пользователь обновлен.")
        return HttpResponseRedirect(self.get_success_url())


class UserDisableView(UserManagementMixin, View):
    def post(self, request, pk):
        User = get_user_model()
        user = get_object_or_404(User, pk=pk)
        before = {"user_id": user.id, "username": user.username, "is_active": user.is_active}
        try:
            disable_local_user(actor=request.user, user=user)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect("settings_center:user_list")
        descriptor = get_registry().get("accounts.users.local_management")
        record_settings_change(
            actor=request.user,
            descriptor=descriptor,
            action=SettingsChange.Action.USER_DISABLE,
            status=SettingsChange.Status.APPLIED,
            before=before,
            after={"user_id": user.id, "username": user.username, "is_active": False},
            validation_result={"valid": True},
        )
        messages.success(request, "Пользователь отключен.")
        return redirect("settings_center:user_list")


class UserADLinkView(UserManagementMixin, FormView):
    template_name = "settings_center/ad_link_form.html"
    form_class = ExternalIdentityForm

    def dispatch(self, request, *args, **kwargs):
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
        before = {}
        if self.identity:
            before = {
                "subject_id": self.identity.subject_id,
                "username": self.identity.username,
                "upn": self.identity.upn,
                "domain": self.identity.domain,
            }
        identity = link_ad_identity(
            actor=self.request.user,
            user=self.portal_user,
            cleaned_data=form.cleaned_data.copy(),
        )
        descriptor = get_registry().get("accounts.user.ad_identity_link")
        record_settings_change(
            actor=self.request.user,
            descriptor=descriptor,
            action=SettingsChange.Action.AD_LINK,
            status=SettingsChange.Status.APPLIED,
            before=before,
            after={
                "subject_id": identity.subject_id,
                "username": identity.username,
                "upn": identity.upn,
                "domain": identity.domain,
            },
            validation_result={"valid": True},
        )
        messages.success(self.request, "AD identity link сохранен.")
        return super().form_valid(form)
