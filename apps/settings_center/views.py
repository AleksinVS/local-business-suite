from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.messages import get_messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from apps.accounts.models import AccessAssignmentAudit, ExternalIdentity
from apps.accounts.access_contracts import (
    apply_role_definition_change,
    can_edit_role_definitions,
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
    apply_external_identity_change,
    apply_role_assignment,
    apply_user_profile_change,
    create_local_user,
    disable_local_user,
    external_identity_audit_snapshot,
    link_ad_identity,
    preview_external_identity_change,
    preview_role_assignment,
    preview_user_profile_change,
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
    AccessExternalIdentityForm,
    ContractPayloadForm,
    EnvProposalForm,
    ExternalIdentityForm,
    HelpQuestionForm,
    MemoryGroupMembershipForm,
    AccessRoleMembershipForm,
    AccessUserDepartmentForm,
    AccessUserBundleForm,
    AccessUserProfileForm,
    AccessUserStatusForm,
    PortalUserCreateForm,
    PortalUserProfileUpdateForm,
    PortalUserUpdateForm,
    RoleDefinitionForm,
    RoleDescriptionForm,
)
from .help_services import answer_help_question, initial_help_text
from .access_bundle_services import apply_user_access_bundle, preview_user_access_bundle
from .models import SettingsChange
from .policies import can_manage_settings
from .registry import get_registry
from .services import record_settings_change
from .access_workspace import workspace_context


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
        return can_edit_role_definitions(self.request.user)


class SettingsDashboardView(SettingsManagementMixin, TemplateView):
    template_name = "settings_center/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["domains"] = get_registry().by_domain()
        context["recent_changes"] = SettingsChange.objects.select_related("actor")[:12]
        context["can_manage_roles"] = can_manage_roles(self.request.user)
        context["can_manage_board_access"] = can_manage_board_access(self.request.user)
        return context


class AccessWorkspaceView(UserManagementMixin, TemplateView):
    """Canonical master-detail access administration shell.

    Existing standalone editors remain the write adapters for now.  The
    workspace owns navigation and read projections; package 07 can attach
    context editors without changing this URL contract.
    """

    template_name = "settings_center/access_workspace.html"
    _HX_TARGETS = {
        "access-field-sidebar-host",
        "access-inspector-host",
        "access-table-panel",
    }

    def test_func(self):
        return bool(
            can_manage_roles(self.request.user)
            or can_edit_role_definitions(self.request.user)
        )

    @staticmethod
    def _is_htmx(request):
        return request.headers.get("HX-Request") == "true"

    @staticmethod
    def _is_history_restore(request):
        return request.headers.get("HX-History-Restore-Request") == "true"

    def _hx_target(self, request):
        target = request.headers.get("HX-Target", "").lstrip("#")
        return f"#{target}" if target in self._HX_TARGETS else ""

    def get(self, request, *args, **kwargs):
        if self._is_htmx(request):
            # htmx history cache misses request the canonical document shell;
            # there is no target header to validate in this mode.
            if self._is_history_restore(request):
                return super().get(request, *args, **kwargs)
            target = self._hx_target(request)
            if not target:
                return HttpResponseBadRequest("Unknown HTMX target.")
            context = self.get_context_data(**kwargs)
            return self._render_hx_panel(context, target)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(workspace_context(query_params=self.request.GET))
        context["field_form"] = self._build_editor_form(self.request, context)
        context["can_manage_board_access"] = can_manage_board_access(self.request.user)
        context["can_manage_roles"] = can_manage_roles(self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        """Dispatch one context editor while preserving the signed service flow."""
        state = workspace_context(query_params=self._post_workspace_params(request))
        try:
            selected = state["selected"]
            if not selected:
                raise ValidationError("Выберите объект доступа.")
            field = state["selected_field"]
            action = request.POST.get("action", "preview")
            if (
                selected["kind"] == "user"
                and self._requested_panel(request) == "inspector"
                and action in {"bundle_preview", "bundle_apply"}
            ):
                return self._post_user_bundle(request, selected, action)
            if action not in {"preview", "apply"}:
                raise ValidationError("Неизвестное действие редактора.")
            if selected["kind"] == "user":
                response = self._post_user(request, selected, field, action)
            elif selected["kind"] == "role":
                response = self._post_role(request, selected, field, action)
            elif selected["kind"] == "board" and field == "groups":
                response = self._post_board(request, selected, action)
            else:
                raise ValidationError("Этот источник доступа доступен только для просмотра.")
            return response
        except (PermissionDenied, ValidationError) as exc:
            state["editor_error"] = str(exc)
            state["field_form"] = self._build_editor_form(request, state)
            return self._response_for_editor(request, state)

    def _post_user_bundle(self, request, selected, action):
        user = selected["user"]
        form = AccessUserBundleForm(
            request.POST,
            portal_user=user,
            actor=request.user,
            ad_identity=selected.get("ad_identity"),
        )
        if not form.is_valid():
            return self._editor_response(request, form, selected)
        cleaned = form.cleaned_data.copy()
        if action == "bundle_preview":
            preview = preview_user_access_bundle(
                actor=request.user,
                target_user=user,
                cleaned_data=cleaned,
            )
            self._set_form_value(form, "preview_token", preview["preview_token"])
            return self._editor_response(request, form, selected, preview=preview)
        reason = cleaned["reason"]
        profile_descriptor = get_registry().get("accounts.users.local_management")
        ad_descriptor = get_registry().get("accounts.user.ad_identity_link")

        def profile_audit_callback(before, after):
            record_settings_change(
                actor=request.user,
                descriptor=profile_descriptor,
                action=SettingsChange.Action.USER_UPDATE,
                status=SettingsChange.Status.APPLIED,
                before=user_profile_audit_snapshot(before),
                after=user_profile_audit_snapshot(after),
                validation_result={"valid": True, "field": "bundle", "reason": reason},
            )

        def ad_audit_callback(before, after):
            record_settings_change(
                actor=request.user,
                descriptor=ad_descriptor,
                action=SettingsChange.Action.AD_LINK,
                status=SettingsChange.Status.APPLIED,
                before=external_identity_audit_snapshot(before),
                after=external_identity_audit_snapshot(after),
                validation_result={"valid": True, "field": "bundle", "reason": reason},
            )

        updated, results = apply_user_access_bundle(
            actor=request.user,
            target_user=user,
            cleaned_data=cleaned,
            preview_token=cleaned["preview_token"],
            risk_confirmed=cleaned["confirm_risk"],
            memory_confirmed=cleaned["confirm_memory"],
            profile_audit_callback=profile_audit_callback,
            ad_audit_callback=ad_audit_callback,
        )
        messages.success(
            request,
            f"Карточка пользователя сохранена. Изменено разделов: {len(results)}.",
        )
        return self._success_response(
            request,
            "users",
            updated.pk,
            cleaned.get("active_editor") or "profile",
        )

    def _render_hx_panel(self, state, target, *, applied=False):
        if target == "#access-field-sidebar-host":
            template = "settings_center/partials/access_workspace/field_apply_response.html" if applied else "settings_center/partials/access_workspace/field_sidebar_response.html"
        elif target == "#access-inspector-host":
            template = "settings_center/partials/access_workspace/inspector_apply_response.html" if applied else "settings_center/partials/access_workspace/inspector_response.html"
        else:
            template = "settings_center/partials/access_workspace/table_panel.html"
        return render(self.request, template, state)

    def _response_for_editor(self, request, state, *, applied=False):
        if not self._is_htmx(request):
            return self.render_to_response(state)
        target = self._hx_target(request)
        if not target:
            return HttpResponseBadRequest("Unknown HTMX target.")
        return self._render_hx_panel(state, target, applied=applied)

    def _success_response(self, request, view, object_id, field):
        if not self._is_htmx(request):
            return redirect(self._workspace_url(view, object_id, field, request=request))
        params = self._post_workspace_params(request)
        params.update({"view": view, "object": object_id, "field": field, "panel": self._requested_panel(request)})
        state = workspace_context(query_params=params)
        state["field_form"] = self._build_editor_form(request, state, use_post=False)
        state["inline_messages"] = list(get_messages(request))
        target = self._hx_target(request)
        if not target:
            return HttpResponseBadRequest("Unknown HTMX target.")
        return self._render_hx_panel(state, target, applied=True)

    def _post_user(self, request, selected, field, action):
        user = selected["user"]
        reason = request.POST.get("reason", "")
        if field in {"profile", "department", "status"}:
            if field == "profile":
                form = AccessUserProfileForm(request.POST, instance=user)
                if not form.is_valid():
                    return self._editor_response(request, form, selected)
                cleaned = form.cleaned_data.copy()
            elif field == "department":
                form = AccessUserDepartmentForm(request.POST)
                if not form.is_valid():
                    return self._editor_response(request, form, selected)
                cleaned = form.cleaned_data.copy()
            else:
                form = AccessUserStatusForm(request.POST)
                if not form.is_valid():
                    return self._editor_response(request, form, selected)
                cleaned = form.cleaned_data.copy()
            reason = cleaned.pop("reason")
            preview_token = cleaned.pop("preview_token", "")
            if action == "preview":
                preview = preview_user_profile_change(
                    actor=request.user,
                    target_user=user,
                    cleaned_data=cleaned,
                    reason=reason,
                )
                self._set_form_value(form, "preview_token", preview["preview_token"])
                return self._editor_response(request, form, selected, preview=preview)
            descriptor = get_registry().get("accounts.users.local_management")

            def audit_callback(before, after):
                record_settings_change(
                    actor=request.user,
                    descriptor=descriptor,
                    action=SettingsChange.Action.USER_UPDATE,
                    status=SettingsChange.Status.APPLIED,
                    before=user_profile_audit_snapshot(before),
                    after=user_profile_audit_snapshot(after),
                    validation_result={"valid": True, "field": field, "reason": reason},
                )

            apply_user_profile_change(
                actor=request.user,
                target_user=user,
                cleaned_data=cleaned,
                preview_token=preview_token,
                reason=reason,
                audit_callback=audit_callback,
            )
            messages.success(request, "Данные пользователя обновлены.")
            return self._success_response(request, "users", user.pk, field)
        if field == "ad":
            form = AccessExternalIdentityForm(request.POST, instance=selected["ad_identity"])
            if not form.is_valid():
                return self._editor_response(request, form, selected)
            cleaned = form.cleaned_data.copy()
            reason = cleaned.pop("reason")
            preview_token = cleaned.pop("preview_token", "")
            if action == "preview":
                preview = preview_external_identity_change(
                    actor=request.user,
                    target_user=user,
                    cleaned_data=cleaned,
                    reason=reason,
                )
                self._set_form_value(form, "preview_token", preview["preview_token"])
                return self._editor_response(request, form, selected, preview=preview)
            descriptor = get_registry().get("accounts.user.ad_identity_link")

            def audit_callback(before, after):
                record_settings_change(
                    actor=request.user,
                    descriptor=descriptor,
                    action=SettingsChange.Action.AD_LINK,
                    status=SettingsChange.Status.APPLIED,
                    before=external_identity_audit_snapshot(before),
                    after=external_identity_audit_snapshot(after),
                    validation_result={"valid": True, "field": "ad", "reason": reason},
                )

            apply_external_identity_change(
                actor=request.user,
                target_user=user,
                cleaned_data=cleaned,
                preview_token=preview_token,
                reason=reason,
                audit_callback=audit_callback,
            )
            messages.success(request, "Связь с AD обновлена.")
            return self._success_response(request, "users", user.pk, field)
        if field == "roles":
            form = PortalUserUpdateForm(request.POST, portal_user=user, actor=request.user)
            return self._post_role_assignment(request, selected, form, action)
        if field == "memory-groups":
            form = MemoryGroupMembershipForm(request.POST)
            if not form.is_valid():
                return self._editor_response(request, form, selected)
            from apps.memory.access_services import apply_memory_group_membership, preview_memory_group_membership
            if action == "preview":
                preview = preview_memory_group_membership(actor=request.user, target_user=user, selected_group_names=form.cleaned_data["group_names"], reason=form.cleaned_data["reason"])
                self._set_form_value(form, "preview_token", preview["preview_token"])
                return self._editor_response(request, form, selected, preview=preview)
            target, audit = apply_memory_group_membership(actor=request.user, target_user=user, selected_group_names=form.cleaned_data["group_names"], reason=form.cleaned_data["reason"], preview_token=form.cleaned_data["preview_token"], confirmed=form.cleaned_data["confirmed"])
            messages.success(request, f"Группы памяти пользователя изменены. Аудит #{audit.pk}.")
            return self._success_response(request, "users", target.pk, field)
        raise ValidationError("Это поле доступно только для просмотра.")

    def _post_role_assignment(self, request, selected, form, action):
        if not form.is_valid():
            return self._editor_response(request, form, selected)
        user = selected["user"]
        selected_role_names = [group.name for group in form.cleaned_data["roles"]]
        if action == "preview":
            preview = preview_role_assignment(actor=request.user, target_user=user, selected_role_names=selected_role_names, is_staff=form.cleaned_data["is_staff"], is_superuser=form.cleaned_data["is_superuser"], reason=form.cleaned_data.get("reason", ""))
            self._set_form_value(form, "preview_token", preview["preview_token"])
            return self._editor_response(request, form, selected, preview=preview)
        updated, audit = apply_role_assignment(actor=request.user, target_user=user, selected_role_names=selected_role_names, preview_token=form.cleaned_data["preview_token"], risk_confirmed=form.cleaned_data["confirm_risk"], is_staff=form.cleaned_data["is_staff"], is_superuser=form.cleaned_data["is_superuser"], reason=form.cleaned_data.get("reason", ""))
        messages.success(request, f"Доступ пользователя сохранён. Аудит #{audit.pk}.")
        return self._success_response(request, "users", updated.pk, "roles")

    def _post_role(self, request, selected, field, action):
        if field in {"definition", "description"}:
            role_model = role_definition_read_model(selected["code"])
            form_class = RoleDescriptionForm if field == "description" else RoleDefinitionForm
            form = form_class(request.POST, role_read_model=role_model)
            if not form.is_valid():
                return self._editor_response(request, form, selected)
            proposed = form.proposed_config()
            if action == "preview":
                preview = preview_role_definition_change(actor=request.user, role_code=selected["code"], proposed_config=proposed, base_hash=form.cleaned_data["base_hash"])
                self._set_form_value(form, "base_hash", preview["base_hash"])
                self._set_form_value(form, "preview_token", preview["preview_token"])
                return self._editor_response(request, form, selected, preview=preview)
            change = apply_role_definition_change(actor=request.user, role_code=selected["code"], proposed_config=proposed, base_hash=form.cleaned_data["base_hash"], preview_token=form.cleaned_data["preview_token"], risk_confirmed=form.cleaned_data["risk_confirmed"])
            messages.success(request, f"Роль изменена. Аудит #{change.pk}.")
            return self._success_response(request, "roles", selected["code"], field)
        if field == "users":
            form = AccessRoleMembershipForm(request.POST, role_name=selected["code"])
            if not form.is_valid():
                return self._editor_response(request, form, selected)
            from apps.accounts.services import apply_role_membership_change, preview_role_membership_change
            ids = form.cleaned_data["selected_user_ids"]
            if action == "preview":
                preview = preview_role_membership_change(actor=request.user, role_name=selected["code"], selected_user_ids=ids, reason=form.cleaned_data["reason"])
                self._set_form_value(form, "preview_token", preview["preview_token"])
                return self._editor_response(request, form, selected, preview=preview)
            audits = apply_role_membership_change(actor=request.user, role_name=selected["code"], selected_user_ids=ids, preview_token=form.cleaned_data["preview_token"], risk_confirmed=form.cleaned_data["risk_confirmed"], reason=form.cleaned_data["reason"])
            messages.success(request, f"Состав роли изменён. Аудитов: {len(audits)}.")
            return self._success_response(request, "roles", selected["code"], "users")
        raise ValidationError("Это поле доступно только для просмотра.")

    def _post_board(self, request, selected, action):
        form = BoardAccessForm(request.POST)
        if not form.is_valid():
            return self._editor_response(request, form, selected)
        if action == "preview":
            preview = preview_board_access(actor=request.user, board=selected["board"], selected_group_names=form.cleaned_data["group_names"], reason=form.cleaned_data["reason"])
            self._set_form_value(form, "preview_token", preview["preview_token"])
            return self._editor_response(request, form, selected, preview=preview)
        board, audit = apply_board_access(actor=request.user, board=selected["board"], selected_group_names=form.cleaned_data["group_names"], preview_token=form.cleaned_data["preview_token"], risk_confirmed=form.cleaned_data["risk_confirmed"], reason=form.cleaned_data["reason"])
        messages.success(request, f"Доступ к доске изменён. Аудит #{audit.pk}.")
        return self._success_response(request, "boards", board.pk, "groups")

    def _editor_response(self, request, form, selected, preview=None):
        state = workspace_context(query_params=self._post_workspace_params(request))
        state.update({"selected": selected, "selected_field": request.POST.get("field", state["selected_field"]), "selected_panel": self._requested_panel(request), "field_form": form, "field_preview": preview})
        return self._response_for_editor(request, state)

    @staticmethod
    def _set_form_value(form, name, value):
        if form.is_bound:
            data = form.data.copy()
            data[name] = value
            form.data = data
        else:
            form.initial[name] = value

    def _build_editor_form(self, request, state, *, use_post=True):
        selected = state.get("selected")
        if not selected:
            return None
        field = state.get("selected_field", "")
        bound_data = request.POST if request.method == "POST" and use_post else None
        if selected["kind"] == "user":
            user = selected["user"]
            if state.get("selected_panel") == "inspector":
                if not can_manage_roles(request.user):
                    return None
                form = AccessUserBundleForm(
                    bound_data,
                    portal_user=user,
                    actor=request.user,
                    ad_identity=selected.get("ad_identity"),
                )
                if not form.is_bound:
                    form.initial["active_editor"] = field or "roles"
                return form
            if not self._can_edit_field(request, selected, field):
                return None
            if field == "profile":
                return AccessUserProfileForm(bound_data, instance=user)
            if field == "status":
                return AccessUserStatusForm(bound_data, initial={"is_active": user.is_active})
            if field == "department":
                return AccessUserDepartmentForm(bound_data, initial={"department": user.department_id})
            if field == "ad":
                return AccessExternalIdentityForm(bound_data, instance=selected["ad_identity"])
            if field == "roles":
                return PortalUserUpdateForm(bound_data, portal_user=user, actor=request.user)
            if field == "memory-groups":
                current = [group["code"] for group in selected["memory_groups"]]
                return MemoryGroupMembershipForm(bound_data, initial={"group_names": current})
        if not self._can_edit_field(request, selected, field):
            return None
        if selected["kind"] == "role":
            if field == "definition":
                model = role_definition_read_model(selected["code"])
                return RoleDefinitionForm(bound_data, role_read_model=model, initial={"base_hash": model["base_hash"]})
            if field == "description":
                model = role_definition_read_model(selected["code"])
                return RoleDescriptionForm(bound_data, role_read_model=model, initial={"base_hash": model["base_hash"]})
            if field == "users":
                current = [user.pk for user in selected.get("user_objects", [])]
                return AccessRoleMembershipForm(bound_data, role_name=selected["code"], initial={"selected_user_ids": current})
        if selected["kind"] == "board" and field == "groups":
            return BoardAccessForm(bound_data, initial={"group_names": selected["group_codes"]})
        return None

    @staticmethod
    def _requested_panel(request):
        return "inspector" if request.POST.get("panel") == "inspector" else "field"

    @staticmethod
    def _post_workspace_params(request):
        params = {
            name: request.POST.get(name, "")
            for name in ("view", "object", "field", "panel")
        }
        for name in ("q", "role", "department", "attention"):
            value = request.POST.get(f"filter_{name}", "")
            if value:
                params[name] = value
        return params

    @staticmethod
    def _can_edit_field(request, selected, field):
        if selected["kind"] == "user" and field in {"profile", "status", "department", "ad", "memory-groups"}:
            return bool(request.user.is_active and request.user.is_superuser)
        if selected["kind"] == "role" and field in {"definition", "description"}:
            return can_edit_role_definitions(request.user)
        if selected["kind"] == "board" and field == "groups":
            return can_manage_board_access(request.user)
        if selected["kind"] == "user" and field == "roles":
            return can_manage_roles(request.user)
        if selected["kind"] == "role" and field == "users":
            return can_manage_roles(request.user)
        return False

    @classmethod
    def _workspace_url(cls, view, object_id, field, *, request=None):
        from urllib.parse import urlencode

        params = {"view": view, "object": object_id, "field": field}
        if request is not None:
            params["panel"] = cls._requested_panel(request)
            for name in ("q", "role", "department", "attention"):
                value = request.POST.get(f"filter_{name}")
                if value:
                    params[name] = value
        else:
            params["panel"] = "field"
        return f"{reverse('settings_center:access_workspace')}?{urlencode(params)}"


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
                        "active_group": form.cleaned_data.get("active_group", ""),
                        "display_name": preview["proposed_config"].get("display_name", ""),
                        "description": preview["proposed_config"].get("description", ""),
                        **{
                            f"capability__{code}": (["*"] if value == "*" else value)
                            for code, value in preview["proposed_config"].items()
                            if code not in {"display_name", "description"}
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
                    reason=form.cleaned_data.get("reason", ""),
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
                reason=form.cleaned_data.get("reason", ""),
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
