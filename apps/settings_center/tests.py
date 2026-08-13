import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.template import Context
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.test.utils import ContextList
from django.urls import reverse

from apps.accounts.models import AccessAssignmentAudit, ExternalIdentity, GroupProfile
from apps.core.contract_store import get_contract, normalized_hash
from apps.core.json_utils import load_json_file
from apps.workorders.models import Board, BoardAccessAudit
from apps.workorders.policies import ROLE_CUSTOMER, ROLE_TECHNICIAN
from apps.memory.models import MemoryGroupMembershipAudit

from .contract_services import (
    apply_contract_payload,
    preview_contract_rollback,
    reconcile_pending_contract_changes,
    rollback_contract_change,
)
from .env_services import create_env_proposal
from .forms import (
    AccessUserProfileForm,
    PortalUserCreateForm,
    PortalUserProfileUpdateForm,
    PortalUserUpdateForm,
    RoleDefinitionForm,
    RoleDescriptionForm,
)
from .help_services import answer_help_question, build_help_context
from .models import SettingsChange, SettingsEnvProposal
from .registry import get_registry


User = get_user_model()
pytestmark = pytest.mark.integration


class AccessWorkspaceTests(TestCase):
    def test_capability_groups_are_complete_and_use_user_facing_sections(self):
        from apps.accounts.access_contracts import capability_group_code, capability_groups
        from apps.accounts.selectors import capability_catalog

        catalog = capability_catalog()
        groups = capability_groups(catalog)
        grouped = [code for group in groups for code, _metadata in group["capabilities"]]
        self.assertEqual(sorted(grouped), sorted(catalog))
        self.assertEqual(len(grouped), len(set(grouped)))
        grouped_map = {code: group["code"] for group in groups for code, _ in group["capabilities"]}
        self.assertEqual(grouped_map["view_scope"], "workorders")
        self.assertEqual(grouped_map["transition_targets"], "workorders")
        self.assertEqual(grouped_map["manage_assignments"], "workorders")
        self.assertEqual(grouped_map["manage_board_columns"], "boards")
        self.assertEqual(grouped_map["manage_inventory"], "inventory")
        self.assertEqual(grouped_map["manage_roles"], "system")
        self.assertEqual(capability_group_code("manage_future", {"type": "flag"}), "administration")
        self.assertEqual(capability_group_code("future_scope", {"type": "scope"}), "access_scopes")
        self.assertEqual(capability_group_code("future_targets", {"type": "targets"}), "access_scopes")
        self.assertEqual(capability_group_code("future_flag", {"type": "flag"}), "other")

    def test_role_inspector_definition_uses_grouped_editor_and_one_active_panel(self):
        actor = User.objects.create_superuser(username="role-group-root", password="pass")
        from apps.accounts.selectors import contract_role_names

        role_name = contract_role_names()[0]
        self.client.force_login(actor)
        response = self.client.get(
            reverse("settings_center:access_workspace"),
            {"view": "roles", "object": role_name, "field": "definition", "panel": "inspector"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "role-capability-editor")
        self.assertContains(response, "role-capability-tab")
        self.assertContains(response, 'name="active_group"', html=False)
        self.assertContains(response, "Технические группы памяти назначаются отдельно")
        self.assertGreaterEqual(len(response.context["field_form"].capability_groups), 1)

    def test_role_definition_form_preserves_active_group_and_all_capabilities(self):
        from apps.accounts.access_contracts import role_definition_read_model
        from apps.accounts.selectors import contract_role_names

        model = role_definition_read_model(contract_role_names()[0])
        data = {
            "base_hash": model["base_hash"],
            "active_group": "memory",
            "display_name": model["label"],
            "description": model["description"],
        }
        for section in model["sections"]:
            for capability in section["capabilities"]:
                value = capability["value"]
                if value is True:
                    data[f"capability__{capability['code']}"] = "on"
                elif value not in (False, None):
                    data[f"capability__{capability['code']}"] = ["*"] if value == "*" else value
        form = RoleDefinitionForm(data, role_read_model=model)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["active_group"], "memory")
        self.assertEqual(form.proposed_config(), model["config"])

    def test_role_definition_form_normalizes_invalid_active_group_and_preserves_valid(self):
        from apps.accounts.access_contracts import role_definition_read_model
        from apps.accounts.selectors import contract_role_names

        model = role_definition_read_model(contract_role_names()[0])
        first = model["sections"][0]["code"]
        valid = RoleDefinitionForm({"active_group": first}, role_read_model=model)
        invalid = RoleDefinitionForm({"active_group": "not-a-group"}, role_read_model=model)
        self.assertEqual(valid["active_group"].value(), first)
        self.assertEqual(invalid["active_group"].value(), first)

    def test_standalone_preview_form_preserves_changed_metadata_in_proposed_config(self):
        from apps.accounts.access_contracts import role_definition_read_model
        from apps.accounts.selectors import contract_role_names

        model = role_definition_read_model(contract_role_names()[0])
        proposed = dict(model["config"])
        proposed.update({"display_name": "Новое название роли", "description": "Новое описание роли"})
        preview_form = RoleDefinitionForm(
            role_read_model=model,
            initial={
                "base_hash": model["base_hash"],
                "active_group": model["sections"][0]["code"],
                "display_name": proposed["display_name"],
                "description": proposed["description"],
                **{
                    f"capability__{code}": (["*"] if value == "*" else value)
                    for code, value in proposed.items()
                    if code not in {"display_name", "description"}
                },
            },
        )
        self.assertEqual(preview_form["display_name"].value(), proposed["display_name"])
        self.assertEqual(preview_form["description"].value(), proposed["description"])
        self.assertEqual(preview_form.proposed_config(), proposed)

    def _bundle_payload(self, *, target, role, memory_group, **overrides):
        payload = {
            "view": "users",
            "object": target.pk,
            "field": "roles",
            "panel": "inspector",
            "username": target.username,
            "first_name": target.first_name,
            "last_name": target.last_name,
            "email": target.email,
            "department": target.department_id,
            "is_active": "on" if target.is_active else "",
            "password": "",
            "ad_provider": ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            "ad_subject_id": "",
            "ad_username": "",
            "ad_upn": "",
            "ad_distinguished_name": "",
            "ad_domain": "",
            "ad_sync_status": ExternalIdentity.SyncStatus.MANUAL,
            "roles": [role.pk] if role else [],
            "is_staff": "on" if target.is_staff else "",
            "is_superuser": "on" if target.is_superuser else "",
            "memory_group_names": [memory_group.name] if memory_group else [],
            "reason": "Пакетная проверка карточки пользователя.",
            "active_editor": "roles",
        }
        payload.update(overrides)
        return payload

    def test_canonical_workspace_exposes_six_tabs_and_user_projection(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="workspace-root", password="pass")
        department = Department.objects.create(name="Центр")
        leaf = Department.objects.create(name="Поддержка", parent=department)
        target = User.objects.create_user(
            username="workspace-target",
            first_name="Анна",
            last_name="Иванова",
            department=leaf,
        )
        role, _ = Group.objects.get_or_create(name="customer")
        technical, _ = Group.objects.get_or_create(name="workspace-technical")
        memory, _ = Group.objects.get_or_create(name="memory_observer")
        target.groups.add(role, technical, memory)
        self.client.force_login(actor)

        response = self.client.get(reverse("settings_center:access_workspace"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [tab["code"] for tab in response.context["tabs"]],
            ["users", "roles", "boards", "site-sections", "technical-groups", "memory-groups"],
        )
        row = next(row for row in response.context["users"] if row["id"] == target.pk)
        self.assertEqual(row["department"], "Поддержка")
        self.assertEqual(row["department_full"], "Центр / Поддержка")
        self.assertEqual([group["code"] for group in row["technical_groups"]], [technical.name])
        self.assertEqual([group["code"] for group in row["memory_groups"]], [memory.name])
        for heading in ("Имя", "Подразделение", "Статус", "Роли", "Разделы сайта", "Технические группы", "Группы памяти"):
            self.assertContains(response, heading)
        self.assertNotContains(response, "<th scope=\"col\">Пользователь AD</th>", html=False)

    def test_workspace_deep_link_selects_field_without_leaving_table(self):
        actor = User.objects.create_superuser(username="workspace-deep-root", password="pass")
        target = User.objects.create_user(username="workspace-deep-target")
        self.client.force_login(actor)

        response = self.client.get(
            reverse("settings_center:access_workspace"),
            {"view": "users", "object": target.pk, "field": "roles"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected"]["id"], target.pk)
        self.assertEqual(response.context["selected_field"], "roles")
        self.assertContains(response, "Основные данные")
        self.assertContains(response, "Редактор значения")
        self.assertContains(response, "workspace-deep-target")

    def test_workspace_panels_use_left_sidebar_and_right_overlay_drawer(self):
        actor = User.objects.create_superuser(username="workspace-panel-root", password="pass")
        target = User.objects.create_user(username="workspace-panel-target")
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")

        inspector_response = self.client.get(
            url,
            {"view": "users", "object": target.pk, "panel": "inspector"},
        )
        self.assertEqual(inspector_response.status_code, 200)
        self.assertContains(inspector_response, "access-inspector-overlay is-active")
        self.assertContains(inspector_response, "drawer drawer-large access-inspector active")
        self.assertContains(inspector_response, 'role="dialog" aria-modal="true"')
        self.assertContains(inspector_response, 'class="access-workspace-grid" inert')
        self.assertNotContains(inspector_response, "access-field-dock")

        field_response = self.client.get(
            url,
            {"view": "users", "object": target.pk, "field": "roles", "panel": "field"},
        )
        self.assertEqual(field_response.status_code, 200)
        self.assertContains(field_response, 'class="access-sidebar-editor"')
        self.assertContains(field_response, 'class="access-context-form"')
        self.assertContains(field_response, 'aria-label="Закрыть редактор поля"')
        self.assertContains(field_response, "sidebar-nav--access")
        self.assertNotContains(field_response, "access-field-dock")

    def test_role_manager_inspector_uses_bundle_with_account_fields_read_only(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        Group.objects.get_or_create(name="customer")
        actor = User.objects.create_user(username="bundle-role-manager")
        actor.groups.add(manager_group)
        target = User.objects.create_user(username="bundle-role-target")
        self.client.force_login(actor)

        response = self.client.get(
            reverse("settings_center:access_workspace"),
            {"view": "users", "object": target.pk, "panel": "inspector"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "access-user-bundle-form")
        self.assertContains(response, "name=\"roles\"", html=False)
        form = response.context["field_form"]
        self.assertFalse(form.fields["roles"].disabled)
        self.assertTrue(form.fields["username"].disabled)
        self.assertTrue(form.fields["department"].disabled)
        self.assertTrue(form.fields["ad_username"].disabled)
        self.assertNotContains(response, 'name="is_staff"', html=False)

    def test_bundle_rejects_duplicate_username_without_writes(self):
        actor = User.objects.create_superuser(username="bundle-duplicate-root", password="pass")
        target = User.objects.create_user(username="bundle-duplicate-target", first_name="До")
        User.objects.create_user(username="bundle-duplicate-existing")
        self.client.force_login(actor)
        response = self.client.post(
            reverse("settings_center:access_workspace"),
            {**self._bundle_payload(target=target, role=None, memory_group=None),
             "action": "bundle_preview", "username": " bundle-duplicate-existing "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже существует")
        target.refresh_from_db()
        self.assertEqual(target.first_name, "До")

    def test_workspace_htmx_gets_return_only_panel_fragments_and_reject_unknown_target(self):
        actor = User.objects.create_superuser(username="workspace-htmx-root", password="pass")
        target = User.objects.create_user(username="workspace-htmx-target")
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        headers = {"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "access-inspector-host"}

        response = self.client.get(url, {"view": "users", "object": target.pk, "panel": "inspector"}, **headers)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<!doctype html>")
        self.assertContains(response, "access-inspector active")
        self.assertContains(response, 'id="access-field-sidebar-host" hx-swap-oob="innerHTML"')

        headers["HTTP_HX_TARGET"] = "unknown-host"
        response = self.client.get(url, {"view": "users"}, **headers)
        self.assertEqual(response.status_code, 400)

    def test_workspace_htmx_history_restore_without_target_returns_full_shell(self):
        actor = User.objects.create_superuser(username="workspace-htmx-history-root", password="pass")
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")

        response = self.client.get(
            url,
            {"view": "users"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_HISTORY_RESTORE_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<!doctype html>", html=False)
        self.assertContains(response, 'data-access-workspace')

    def test_user_inspector_bundle_previews_and_applies_all_components_atomically(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="bundle-root", password="pass")
        department = Department.objects.create(name="Bundle before")
        next_department = Department.objects.create(name="Bundle after")
        target = User.objects.create_user(
            username="bundle-target",
            first_name="До",
            department=department,
        )
        customer, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        technician, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        observer, _ = Group.objects.get_or_create(name="memory_observer")
        target.groups.add(customer)
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        payload = self._bundle_payload(
            target=target,
            role=technician,
            memory_group=observer,
            first_name="После",
            department=next_department.pk,
            ad_username="bundle-ad-user",
            ad_upn="bundle-ad-user@example.test",
        )

        preview_response = self.client.post(url, {**payload, "action": "bundle_preview"})
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.context["field_preview"]
        self.assertEqual(
            set(preview["components"]),
            {"profile", "ad", "roles", "memory"},
        )
        apply_response = self.client.post(
            url,
            {
                **payload,
                "action": "bundle_apply",
                "preview_token": preview["preview_token"],
                "confirm_risk": "on",
                "confirm_memory": "on",
            },
        )

        self.assertEqual(apply_response.status_code, 302)
        target.refresh_from_db()
        self.assertEqual(target.first_name, "После")
        self.assertEqual(target.department_id, next_department.pk)
        self.assertEqual(
            set(target.groups.values_list("name", flat=True)),
            {ROLE_TECHNICIAN, "memory_observer"},
        )
        self.assertEqual(target.external_identities.get().username, "bundle-ad-user")
        self.assertEqual(AccessAssignmentAudit.objects.filter(target_user=target).count(), 1)
        self.assertEqual(MemoryGroupMembershipAudit.objects.filter(target_user=target).count(), 1)
        self.assertEqual(SettingsChange.objects.filter(actor=actor).count(), 2)

    def test_user_inspector_bundle_rolls_back_earlier_components_when_late_ad_check_fails(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="bundle-rollback-root", password="pass")
        department = Department.objects.create(name="Bundle rollback")
        target = User.objects.create_user(
            username="bundle-rollback-target",
            first_name="До",
            department=department,
        )
        customer, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        technician, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        observer, _ = Group.objects.get_or_create(name="memory_observer")
        target.groups.add(customer)
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        payload = self._bundle_payload(
            target=target,
            role=technician,
            memory_group=observer,
            first_name="После",
            ad_username="bundle-before-preview",
        )
        preview_response = self.client.post(url, {**payload, "action": "bundle_preview"})
        preview = preview_response.context["field_preview"]

        apply_response = self.client.post(
            url,
            {
                **payload,
                "action": "bundle_apply",
                "preview_token": preview["preview_token"],
                "confirm_risk": "on",
                "confirm_memory": "on",
                "ad_username": "bundle-after-preview",
            },
        )

        self.assertEqual(apply_response.status_code, 200)
        self.assertContains(apply_response, "изменились после предпросмотра")
        target.refresh_from_db()
        self.assertEqual(target.first_name, "До")
        self.assertEqual(
            set(target.groups.values_list("name", flat=True)),
            {ROLE_CUSTOMER},
        )
        self.assertFalse(target.external_identities.exists())
        self.assertFalse(AccessAssignmentAudit.objects.filter(target_user=target).exists())
        self.assertFalse(MemoryGroupMembershipAudit.objects.filter(target_user=target).exists())
        self.assertFalse(SettingsChange.objects.filter(actor=actor).exists())

    def test_workspace_htmx_preview_and_apply_refresh_panel_and_table(self):
        from apps.accounts.selectors import contract_role_names

        actor = User.objects.create_superuser(username="workspace-htmx-apply-root", password="pass")
        target = User.objects.create_user(username="workspace-htmx-apply-target")
        role_name = contract_role_names()[0]
        role, _ = Group.objects.get_or_create(name=role_name)
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        payload = {
            "view": "users", "object": target.pk, "field": "roles", "panel": "field",
            "action": "preview", "roles": [role.pk], "is_staff": "", "is_superuser": "",
            "reason": "HTMX-проверка назначения роли.",
        }
        headers = {"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "access-field-sidebar-host"}

        preview_response = self.client.post(url, payload, **headers)

        self.assertEqual(preview_response.status_code, 200)
        self.assertNotContains(preview_response, "<!doctype html>")
        self.assertContains(preview_response, "Предпросмотр изменения")
        self.assertContains(preview_response, 'data-access-dirty="true"')
        self.assertContains(preview_response, 'id="access-inspector-host" hx-swap-oob="innerHTML"')
        payload.update(action="apply", preview_token=preview_response.context["field_preview"]["preview_token"], confirm_risk="on")
        apply_response = self.client.post(url, payload, **headers)

        self.assertEqual(apply_response.status_code, 200)
        self.assertNotIn("HX-Redirect", apply_response.headers)
        self.assertContains(apply_response, 'id="access-table-panel" hx-swap-oob="innerHTML"')
        self.assertContains(apply_response, "Доступ пользователя сохранён")
        self.assertTrue(target.groups.filter(pk=role.pk).exists())
        next_full_response = self.client.get(url)
        self.assertNotContains(next_full_response, "Доступ пользователя сохранён")

    def test_inline_role_assignment_uses_preview_then_apply_service(self):
        from apps.accounts.selectors import contract_role_names

        actor = User.objects.create_superuser(username="workspace-inline-root", password="pass")
        target = User.objects.create_user(username="workspace-inline-target")
        role_name = contract_role_names()[0]
        role, _ = Group.objects.get_or_create(name=role_name)
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        response = self.client.post(
            url,
            {
                "view": "users",
                "object": target.pk,
                "field": "roles",
                "panel": "field",
                "action": "preview",
                "roles": [role.pk],
                "is_staff": "",
                "is_superuser": "",
                "reason": "Проверка назначения роли через карточку.",
            },
        )
        self.assertEqual(response.status_code, 200)
        preview = response.context["field_preview"]
        self.assertTrue(preview["preview_token"])
        response = self.client.post(
            url,
            {
                "view": "users",
                "object": target.pk,
                "field": "roles",
                "panel": "field",
                "action": "apply",
                "roles": [role.pk],
                "is_staff": "",
                "is_superuser": "",
                "reason": "Проверка назначения роли через карточку.",
                "preview_token": preview["preview_token"],
                "confirm_risk": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(target.groups.filter(pk=role.pk).exists())

    def test_inline_role_membership_uses_bulk_preview_apply_and_audits_target(self):
        from apps.accounts.selectors import contract_role_names

        actor = User.objects.create_superuser(username="workspace-bulk-root", password="pass")
        target = User.objects.create_user(username="workspace-bulk-target")
        role_name = contract_role_names()[0]
        Group.objects.get_or_create(name=role_name)
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        payload = {
            "view": "roles",
            "object": role_name,
            "field": "users",
            "panel": "field",
            "action": "preview",
            "selected_user_ids": [target.pk],
            "reason": "Проверка состава роли через карточку.",
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        preview = response.context["field_preview"]
        self.assertEqual(preview["changed_count"], 1)
        payload.update(
            action="apply",
            preview_token=preview["preview_token"],
            risk_confirmed="on",
        )
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(target.groups.filter(name=role_name).exists())
        self.assertEqual(AccessAssignmentAudit.objects.filter(target_user=target).count(), 1)

    def test_workspace_role_membership_read_model_ignores_user_filters(self):
        from apps.accounts.selectors import contract_role_names

        actor = User.objects.create_superuser(username="workspace-filter-root", password="pass")
        member = User.objects.create_user(username="workspace-hidden-member")
        role_name = contract_role_names()[0]
        role, _ = Group.objects.get_or_create(name=role_name)
        member.groups.add(role)
        self.client.force_login(actor)

        response = self.client.get(
            reverse("settings_center:access_workspace"),
            {"view": "roles", "object": role_name, "field": "users", "q": "no-match"},
        )

        self.assertEqual(response.status_code, 200)
        selected = response.context["selected"]
        self.assertIn(member.pk, [user.pk for user in selected["user_objects"]])
        self.assertEqual(response.context["users"], [])

    def test_workspace_builds_deep_department_paths_from_one_department_query(self):
        from apps.core.models import Department
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .access_workspace import workspace_context

        parent = None
        for index in range(5):
            parent = Department.objects.create(name=f"Узел {index}", parent=parent)
        User.objects.create_user(username="workspace-deep-department", department=parent)

        with CaptureQueriesContext(connection) as queries:
            context = workspace_context(query_params={})

        department_queries = [
            query for query in queries
            if 'FROM "core_department"' in query["sql"] and "JOIN" not in query["sql"]
        ]
        self.assertEqual(len(department_queries), 1)
        row = next(row for row in context["users"] if row["username"] == "workspace-deep-department")
        self.assertEqual(row["department_full"], " / ".join(f"Узел {index}" for index in range(5)))

    def test_workspace_marks_default_board_viewer_as_read_only_source(self):
        actor = User.objects.create_superuser(username="workspace-default-root", password="pass")
        target = User.objects.create_user(username="workspace-default-target", is_active=True)
        self.client.force_login(actor)

        response = self.client.get(reverse("settings_center:access_workspace"))

        row = next(row for row in response.context["users"] if row["id"] == target.pk)
        self.assertEqual(row["role_codes"], [])
        self.assertEqual(row["roles"], ["Базовый просмотр канбана"])
        self.assertTrue(row["role_sources"][0]["read_only"])

    def test_profile_editor_requires_signed_preview_and_keeps_inspector_panel(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="workspace-profile-root", password="pass")
        department = Department.objects.create(name="Рабочее подразделение")
        target = User.objects.create_user(
            username="workspace-profile-target",
            email="before@example.test",
            department=department,
        )
        self.client.force_login(actor)
        url = reverse("settings_center:access_workspace")
        payload = {
            "view": "users",
            "object": target.pk,
            "field": "profile",
            "panel": "inspector",
            "action": "preview",
            "username": target.username,
            "first_name": "Ирина",
            "last_name": "Петрова",
            "email": "after@example.test",
            "department": department.pk,
            "is_active": "on",
            "password": "",
            "reason": "Уточнение рабочего профиля",
        }

        preview_response = self.client.post(url, payload)

        self.assertEqual(preview_response.status_code, 200)
        self.assertIsInstance(preview_response.context["field_form"], AccessUserProfileForm)
        self.assertEqual(preview_response.context["selected_panel"], "inspector")
        preview = preview_response.context["field_preview"]
        self.assertTrue(preview["preview_token"])

        payload.update(action="apply", preview_token=preview["preview_token"])
        apply_response = self.client.post(url, payload)

        self.assertEqual(apply_response.status_code, 302)
        self.assertIn("panel=inspector", apply_response["Location"])
        target.refresh_from_db()
        self.assertEqual(target.email, "after@example.test")

    def test_profile_apply_without_preview_is_rejected(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="workspace-no-preview-root", password="pass")
        department = Department.objects.create(name="Отдел без preview")
        target = User.objects.create_user(
            username="workspace-no-preview-target",
            email="before@example.test",
            department=department,
        )
        self.client.force_login(actor)

        response = self.client.post(
            reverse("settings_center:access_workspace"),
            {
                "view": "users",
                "object": target.pk,
                "field": "profile",
                "panel": "field",
                "action": "apply",
                "username": target.username,
                "first_name": "",
                "last_name": "",
                "email": "forbidden@example.test",
                "department": department.pk,
                "is_active": "on",
                "password": "",
                "reason": "Попытка без предпросмотра",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сначала выполните предпросмотр")
        target.refresh_from_db()
        self.assertEqual(target.email, "before@example.test")

    def test_invalid_editor_response_keeps_dirty_navigation_guard_enabled(self):
        actor = User.objects.create_superuser(username="workspace-invalid-root", password="pass")
        target = User.objects.create_user(username="workspace-invalid-target")
        self.client.force_login(actor)

        response = self.client.post(
            reverse("settings_center:access_workspace"),
            {
                "view": "users",
                "object": target.pk,
                "field": "profile",
                "panel": "inspector",
                "action": "preview",
                "username": "",
                "reason": "Проверка ошибки формы",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["field_form"].errors)
        self.assertContains(response, 'data-access-dirty="true"')

    def test_role_description_cell_uses_dedicated_form(self):
        from apps.accounts.access_contracts import role_definition_read_model
        from apps.accounts.selectors import contract_role_names

        actor = User.objects.create_superuser(username="workspace-description-root", password="pass")
        role_name = contract_role_names()[0]
        self.client.force_login(actor)

        response = self.client.get(
            reverse("settings_center:access_workspace"),
            {"view": "roles", "object": role_name, "field": "description", "panel": "field"},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["field_form"]
        self.assertIsInstance(form, RoleDescriptionForm)
        self.assertEqual(form["description"].value(), role_definition_read_model(role_name)["description"])

    def test_role_description_form_allows_clearing_existing_description(self):
        from apps.accounts.access_contracts import role_definition_read_model
        from apps.accounts.selectors import contract_role_names

        role_model = role_definition_read_model(contract_role_names()[0])
        form = RoleDescriptionForm(
            {"description": "", "base_hash": role_model["base_hash"]},
            role_read_model=role_model,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.proposed_config()["description"], "")


class SettingsCenterRegistryTests(TestCase):
    def test_access_administration_e2e_command(self):
        output = StringIO()

        call_command("access_administration_e2e", stdout=output)

        self.assertIn("access_administration_e2e: OK", output.getvalue())
        self.assertFalse(User.objects.filter(username__startswith="__access_admin_e2e_").exists())

    def test_access_e2e_response_context_supports_context_list_and_checks_status(self):
        from .management.commands.access_administration_e2e import Command

        response = SimpleNamespace(
            status_code=200,
            context_data=object(),
            context=ContextList(
                [
                    Context({"shared": "first", "first_only": 1}),
                    Context({"shared": "second", "second_only": 2}),
                ]
            ),
        )

        context = Command._response_context(response, label="тестовый ответ")

        self.assertEqual(context["shared"], "first")
        self.assertEqual(context["first_only"], 1)
        self.assertEqual(context["second_only"], 2)
        with self.assertRaisesMessage(CommandError, "статус 403"):
            Command._response_context(
                SimpleNamespace(status_code=403, context_data={}),
                label="запрещённый ответ",
            )

    def test_registry_loads_domain_descriptors(self):
        registry = get_registry()
        setting_ids = {descriptor.setting_id for descriptor in registry.all()}

        self.assertIn("core.contract.role_rules", setting_ids)
        self.assertIn("accounts.user.ad_identity_link", setting_ids)
        self.assertIn("workorders.contract.status_colors", setting_ids)
        self.assertIn("ai.contract.tools", setting_ids)
        self.assertIn("memory.source.acl_mode", setting_ids)
        self.assertIn("settings_center.env.OPENAI_API_KEY", setting_ids)
        self.assertIn("settings_center.env.LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED", setting_ids)

    def test_dashboard_requires_staff(self):
        staff = User.objects.create_user(username="settings-staff", password="pass", is_staff=True)
        regular = User.objects.create_user(username="settings-regular", password="pass")

        self.client.force_login(regular)
        self.assertEqual(self.client.get(reverse("settings_center:dashboard")).status_code, 403)

        self.client.force_login(staff)
        response = self.client.get(reverse("settings_center:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Центр настроек")
        self.assertContains(response, "Режим входа Django")
        self.assertContains(response, "settings_center.env.DJANGO_AUTH_MODE")
        self.assertNotContains(response, reverse("settings_center:user_list"))

    def test_setting_detail_shows_russian_title_and_english_identifier(self):
        staff = User.objects.create_user(username="settings-detail-staff", password="pass", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(
            reverse(
                "settings_center:setting_detail",
                kwargs={"setting_id": "settings_center.env.DJANGO_AUTH_MODE"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Режим входа Django")
        self.assertContains(response, "settings_center.env.DJANGO_AUTH_MODE")

    def test_role_rules_generic_editor_redirects_to_protected_card_editor(self):
        staff = User.objects.create_user(username="settings-role-staff", password="pass", is_staff=True)
        self.client.force_login(staff)

        url = reverse(
            "settings_center:setting_detail",
            kwargs={"setting_id": "core.contract.role_rules"},
        )
        response = self.client.post(url, {"action": "apply", "payload": "{}", "confirm": "on"})

        self.assertRedirects(response, reverse("settings_center:role_catalog"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(response["Location"]).status_code, 403)

    def test_env_status_shows_russian_title_and_english_keys(self):
        staff = User.objects.create_user(username="settings-env-staff", password="pass", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse("settings_center:env_status"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Режим входа Django")
        self.assertContains(response, "settings_center.env.DJANGO_AUTH_MODE")
        self.assertContains(response, "DJANGO_AUTH_MODE")

    def test_help_ask_route_uses_setting_context(self):
        staff = User.objects.create_user(username="settings-help-staff", password="pass", is_staff=True)
        self.client.force_login(staff)

        response = self.client.post(
            reverse(
                "settings_center:help_ask",
                kwargs={"setting_id": "settings_center.env.DJANGO_AUTH_MODE"},
            ),
            {"question": "Что делает настройка?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "settings_center.env.DJANGO_AUTH_MODE")

    def test_board_access_workspace_uses_preview_before_apply(self):
        actor = User.objects.create_superuser(username="board-settings-admin", password="pass")
        customer, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        technician, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        board = Board.objects.create(title="Доска центра настроек", slug="settings-board")
        board.allowed_groups.add(customer)
        self.client.force_login(actor)

        self.assertEqual(self.client.get(reverse("settings_center:board_access_list")).status_code, 200)
        url = reverse("settings_center:board_access", args=[board.pk])
        response = self.client.post(
            url,
            {
                "action": "preview",
                "group_names": [ROLE_CUSTOMER, ROLE_TECHNICIAN],
                "reason": "Рабочая группа техников",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Проверка изменения")
        preview = response.context["preview"]
        response = self.client.post(
            url,
            {
                "action": "apply",
                "group_names": [ROLE_CUSTOMER, ROLE_TECHNICIAN],
                "reason": "Рабочая группа техников",
                "preview_token": preview["preview_token"],
                "risk_confirmed": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(board.allowed_groups.filter(pk=technician.pk).exists())
        self.assertEqual(
            BoardAccessAudit.objects.get(board=board).source,
            BoardAccessAudit.Source.SETTINGS_CENTER,
        )

    def test_single_role_workspace_previews_impact_and_changes_only_selected_role(self):
        from apps.core.contract_store import _reset_for_tests

        actor = User.objects.create_superuser(username="role-catalog-admin", password="pass")
        role_rules = load_json_file("contracts/role_rules.json")
        role_code = next(role for role in role_rules if not role.startswith("$"))
        sibling_code = next(
            role for role in role_rules if not role.startswith("$") and role != role_code
        )
        member = User.objects.create_user(username="role-impact-member", password="pass")
        role_group, _ = Group.objects.get_or_create(name=role_code)
        member.groups.add(role_group)

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(role_rules, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                self.client.force_login(actor)
                catalog = self.client.get(reverse("settings_center:role_catalog"))
                self.assertEqual(catalog.status_code, 200)
                self.assertContains(catalog, role_rules[role_code].get("display_name", role_code))

                url = reverse("settings_center:role_definition", args=[role_code])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                form = response.context["form"]
                post_data = {
                    "action": "preview",
                    "base_hash": response.context["role"]["base_hash"],
                    "display_name": "Роль после предпросмотра",
                    "description": "Описание, сохранённое между проверкой и применением.",
                }
                changed_code = "create_workorder"
                for field_name, field in form.fields.items():
                    if not field_name.startswith("capability__"):
                        continue
                    capability = field_name.removeprefix("capability__")
                    current = role_rules[role_code][capability]
                    if capability == changed_code:
                        current = not current
                    if isinstance(current, bool):
                        if current:
                            post_data[field_name] = "on"
                    elif current == "*":
                        post_data[field_name] = ["*"]
                    elif isinstance(current, list):
                        post_data[field_name] = current
                    else:
                        post_data[field_name] = current
                preview_response = self.client.post(url, post_data)
                self.assertEqual(preview_response.status_code, 200)
                preview = preview_response.context["preview"]
                self.assertEqual(preview["impact"]["role_member_count"], 1)
                self.assertEqual(
                    {item["code"] for item in preview["changes"]},
                    {"display_name", "description", changed_code},
                )
                self.assertEqual(
                    preview_response.context["form"]["display_name"].value(),
                    "Роль после предпросмотра",
                )
                self.assertEqual(
                    preview_response.context["form"]["description"].value(),
                    "Описание, сохранённое между проверкой и применением.",
                )

                post_data.update(
                    action="apply",
                    preview_token=preview["preview_token"],
                    risk_confirmed="on",
                )
                apply_response = self.client.post(url, post_data)
                self.assertEqual(apply_response.status_code, 302)
                saved = load_json_file(role_file)
                self.assertEqual(saved[role_code][changed_code], not role_rules[role_code][changed_code])
                self.assertEqual(saved[role_code]["display_name"], "Роль после предпросмотра")
                self.assertEqual(
                    saved[role_code]["description"],
                    "Описание, сохранённое между проверкой и применением.",
                )
                self.assertEqual(saved[sibling_code], role_rules[sibling_code])

    def test_role_editor_service_rejects_unknown_proposed_capability(self):
        from apps.accounts.access_contracts import preview_role_definition_change
        from apps.core.contract_store import _reset_for_tests

        actor = User.objects.create_superuser(username="role-unknown-admin")
        role_rules = load_json_file("contracts/role_rules.json")
        role_code = next(role for role in role_rules if not role.startswith("$"))
        proposed = {
            code: copy.deepcopy(role_rules[role_code][code])
            for code in role_rules["$capabilities"]
        }
        proposed["unknown_capability"] = True
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(role_rules, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                with self.assertRaisesMessage(ValidationError, "неизвестные права"):
                    preview_role_definition_change(
                        actor=actor,
                        role_code=role_code,
                        proposed_config=proposed,
                        base_hash=normalized_hash(role_rules),
                    )

    def test_role_preview_rejects_member_change_before_apply(self):
        from apps.accounts.access_contracts import (
            apply_role_definition_change,
            preview_role_definition_change,
            role_definition_read_model,
        )
        from apps.accounts.selectors import capability_catalog
        from apps.core.contract_store import _reset_for_tests

        actor = User.objects.create_superuser(username="role-member-stale-root")
        role_rules = load_json_file("contracts/role_rules.json")
        role_code = next(role for role in role_rules if not role.startswith("$"))
        role_group, _ = Group.objects.get_or_create(name=role_code)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(role_rules, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                read_model = role_definition_read_model(role_code)
                proposed = {
                    code: read_model["config"].get(code) for code in capability_catalog()
                }
                proposed["create_workorder"] = not proposed["create_workorder"]
                preview = preview_role_definition_change(
                    actor=actor,
                    role_code=role_code,
                    proposed_config=proposed,
                    base_hash=read_model["base_hash"],
                )
                new_member = User.objects.create_user(username="late-role-member")
                new_member.groups.add(role_group)

                with self.assertRaisesMessage(ValidationError, "Состав участников роли"):
                    apply_role_definition_change(
                        actor=actor,
                        role_code=role_code,
                        proposed_config=proposed,
                        base_hash=read_model["base_hash"],
                        preview_token=preview["preview_token"],
                        risk_confirmed=True,
                    )

    def test_role_contract_apply_rejects_actor_disabled_after_preview(self):
        from apps.accounts.access_contracts import (
            apply_role_definition_change,
            preview_role_definition_change,
            role_definition_read_model,
        )
        from apps.accounts.selectors import capability_catalog
        from apps.accounts.services import disable_local_user
        from apps.core.contract_store import _reset_for_tests

        actor = User.objects.create_superuser(username="role-lifecycle-root")
        lifecycle_operator = User.objects.create_superuser(username="role-lifecycle-operator")
        role_rules = load_json_file("contracts/role_rules.json")
        role_code = next(role for role in role_rules if not role.startswith("$"))
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(role_rules, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                read_model = role_definition_read_model(role_code)
                proposed = {
                    code: read_model["config"].get(code) for code in capability_catalog()
                }
                proposed["create_workorder"] = not proposed["create_workorder"]
                preview = preview_role_definition_change(
                    actor=actor,
                    role_code=role_code,
                    proposed_config=proposed,
                    base_hash=read_model["base_hash"],
                )
                disable_local_user(actor=lifecycle_operator, user=actor)

                with self.assertRaises(PermissionDenied):
                    apply_role_definition_change(
                        actor=actor,
                        role_code=role_code,
                        proposed_config=proposed,
                        base_hash=preview["base_hash"],
                        preview_token=preview["preview_token"],
                        risk_confirmed=True,
                    )
                self.assertEqual(load_json_file(role_file), role_rules)

    def test_role_impact_normalizes_dominating_all_scope(self):
        from apps.accounts.access_contracts import _effective_role_values

        configs = {
            "broad": {"view_scope": "all"},
            "narrow": {"view_scope": "authored"},
        }
        effective = _effective_role_values(["broad", "narrow"], configs)

        self.assertEqual(effective["view_scope"], ["all"])

    def test_role_impact_keeps_transition_scope_and_target_paired_per_role(self):
        from apps.accounts.access_contracts import _effective_role_values

        configs = {
            "first": {
                "transition_scope": "authored",
                "transition_targets": ["accepted"],
            },
            "second": {
                "transition_scope": "assigned",
                "transition_targets": ["resolved"],
            },
        }
        before = _effective_role_values(["first", "second"], configs)
        changed = copy.deepcopy(configs)
        changed["first"]["transition_targets"] = ["resolved"]
        after = _effective_role_values(["first", "second"], changed)

        self.assertNotEqual(before["transition_grants"], after["transition_grants"])

    def test_role_impact_normalizes_nested_transition_scopes(self):
        from apps.accounts.access_contracts import _effective_role_values

        configs = {
            "broad": {
                "transition_scope": "assigned_or_unassigned",
                "transition_targets": ["resolved"],
            },
            "narrow": {
                "transition_scope": "assigned",
                "transition_targets": ["resolved"],
            },
        }

        effective = _effective_role_values(["broad", "narrow"], configs)

        self.assertEqual(
            effective["transition_grants"],
            [("assigned_or_unassigned", "resolved")],
        )


class SettingsCenterContractTests(TestCase):
    def test_role_contract_service_rejects_non_superuser_direct_call(self):
        actor = User.objects.create_user(username="settings-role-manager")
        manager_group, _ = Group.objects.get_or_create(name="manager")
        actor.groups.add(manager_group)
        payload = load_json_file("contracts/role_rules.json")

        with self.assertRaisesMessage(PermissionDenied, "только суперпользователь"):
            apply_contract_payload(
                actor=actor,
                setting_id="core.contract.role_rules",
                raw_payload=json.dumps(payload, ensure_ascii=False),
                confirmed=True,
            )

    def test_runtime_contract_apply_validates_writes_atomically_and_audits(self):
        actor = User.objects.create_superuser(username="settings-admin", password="pass")
        with TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            payload = load_json_file("contracts/role_rules.json")
            role_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            changed_payload = {**payload}
            first_role = next(role for role in changed_payload if not role.startswith("$"))
            changed_payload[first_role] = {**changed_payload[first_role], "display_name": "Changed role name"}

            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                LOCAL_BUSINESS_ROLE_RULES=payload,
                RUNTIME_CONTRACTS_DIR=Path(tmpdir),
            ):
                change = apply_contract_payload(
                    actor=actor,
                    setting_id="core.contract.role_rules",
                    raw_payload=json.dumps(changed_payload, ensure_ascii=False),
                    confirmed=True,
                    base_hash=normalized_hash(payload),
                )

            self.assertEqual(change.status, SettingsChange.Status.APPLIED)
            self.assertTrue(change.masked_diff["changed"])
            self.assertEqual(load_json_file(role_file)[first_role]["display_name"], "Changed role name")

    def test_apply_with_stale_base_hash_is_rejected(self):
        from apps.core.contract_store import _reset_for_tests

        actor = User.objects.create_superuser(username="stale-admin", password="pass")
        with TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            payload = load_json_file("contracts/role_rules.json")
            role_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            first_role = next(role for role in payload if not role.startswith("$"))

            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=Path(tmpdir),
            ):
                _reset_for_tests()
                self.addCleanup(_reset_for_tests)
                # Читаем версию, которую собираемся править, и запоминаем её хеш.
                stale_hash = normalized_hash(get_contract("role_rules"))

                # Конкурентная правка того же файла другим процессом.
                concurrent = copy.deepcopy(payload)
                concurrent[first_role]["display_name"] = "Concurrent change"
                role_file.write_text(json.dumps(concurrent, ensure_ascii=False), encoding="utf-8")

                attempted = copy.deepcopy(payload)
                attempted[first_role]["display_name"] = "My lost update"
                with self.assertRaisesMessage(ValidationError, "изменён другим процессом"):
                    apply_contract_payload(
                        actor=actor,
                        setting_id="core.contract.role_rules",
                        raw_payload=json.dumps(attempted, ensure_ascii=False),
                        confirmed=True,
                        base_hash=stale_hash,
                    )

                # Потерянного обновления нет: на диске осталась конкурентная версия.
                saved = load_json_file(role_file)
                self.assertEqual(saved[first_role]["display_name"], "Concurrent change")

    def test_workflow_transition_matrix_view_can_deny_all_transitions(self):
        actor = User.objects.create_user(username="workflow-admin", password="pass", is_staff=True)
        payload = load_json_file("contracts/workflow_rules.json")
        with TemporaryDirectory() as tmpdir:
            workflow_file = Path(tmpdir) / "workflow_rules.json"
            workflow_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_WORKFLOW_RULES_FILE=workflow_file,
                LOCAL_BUSINESS_WORKFLOW_RULES=payload,
                RUNTIME_CONTRACTS_DIR=Path(tmpdir),
            ):
                self.client.force_login(actor)
                response = self.client.get(reverse("settings_center:workflow_transitions"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Переходы статусов")
                base_hash = response.context["base_hash"]

                response = self.client.post(
                    reverse("settings_center:workflow_transitions"),
                    {"action": "deny_all", "confirm": "on", "base_hash": base_hash},
                )

                self.assertEqual(response.status_code, 302)
                saved = load_json_file(workflow_file)
                for source in payload["statuses"]:
                    self.assertEqual(saved["transitions"][source], [])
                # После ADR-0031 согласованность обеспечивает contract store, а не
                # присваивание settings.* в текущем воркере: store перечитывает
                # обновлённый файл по ключу метаданных.
                self.assertEqual(get_contract("workflow_rules"), saved)
            self.assertEqual(SettingsChange.objects.filter(setting_id="core.contract.workflow_rules").count(), 1)

    def test_workorder_status_color_palette_view_updates_contract(self):
        actor = User.objects.create_user(username="color-admin", password="pass", is_staff=True)
        payload = load_json_file("contracts/workorder_status_colors.json")
        with TemporaryDirectory() as tmpdir:
            color_file = Path(tmpdir) / "workorder_status_colors.json"
            color_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE=color_file,
                LOCAL_BUSINESS_WORKORDER_STATUS_COLORS=payload,
                RUNTIME_CONTRACTS_DIR=Path(tmpdir),
            ):
                self.client.force_login(actor)
                response = self.client.get(reverse("settings_center:workorder_status_colors"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Цвета статусов заявок")

                post_data = {"confirm": "on", "base_hash": response.context["base_hash"]}
                for status, config in payload["statuses"].items():
                    post_data[f"color__{status}"] = "#111111" if status == "new" else config["color"]
                    post_data[f"background__{status}"] = config["background"]

                response = self.client.post(reverse("settings_center:workorder_status_colors"), post_data)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(load_json_file(color_file)["statuses"]["new"]["color"], "#111111")


class SettingsContractRecoveryTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.actor = User.objects.create_superuser(username="recovery-admin", password="pass")
        self.payload = load_json_file("contracts/role_rules.json")

    def _changed(self, label):
        changed = copy.deepcopy(self.payload)
        first_role = next(role for role in changed if not role.startswith("$"))
        changed[first_role]["display_name"] = label
        return changed

    def test_role_contract_direct_service_rejects_wrong_type_unknown_and_incomplete_role(self):
        from .contract_services import parse_and_validate_payload

        descriptor = get_registry().get("core.contract.role_rules")
        role = next(key for key in self.payload if not key.startswith("$"))
        invalid_payloads = []

        wrong_type = copy.deepcopy(self.payload)
        wrong_type[role]["create_workorder"] = "false"
        invalid_payloads.append(wrong_type)

        unknown_capability = copy.deepcopy(self.payload)
        unknown_capability[role]["unknown_capability"] = True
        invalid_payloads.append(unknown_capability)

        incomplete = copy.deepcopy(self.payload)
        incomplete[role].pop("view_scope")
        invalid_payloads.append(incomplete)

        for payload in invalid_payloads:
            with self.subTest(payload=payload[role]), self.assertRaises(ValidationError):
                parse_and_validate_payload(
                    descriptor,
                    json.dumps(payload, ensure_ascii=False),
                )

    @pytest.mark.slow
    def test_two_process_writers_yield_one_apply_and_one_stale_conflict(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_root = root / "data"
            runtime_root = data_root / "contracts"
            shutil.copytree(Path(settings.BASE_DIR) / "contracts", runtime_root)
            role_file = runtime_root / "role_rules.json"
            database_file = root / "shared.sqlite3"
            role_file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
            base_hash = normalized_hash(self.payload)
            env = os.environ.copy()
            env.update(
                {
                    "DJANGO_ENV": "development",
                    "LOCAL_BUSINESS_DB_BACKEND": "sqlite",
                    "LOCAL_BUSINESS_DATA_DIR": str(data_root),
                    "LOCAL_BUSINESS_SQLITE_PATH": str(database_file),
                    "LOCAL_BUSINESS_ROLE_RULES_FILE": str(role_file),
                }
            )
            migrate = subprocess.run(
                [sys.executable, "manage.py", "migrate", "--noinput", "--verbosity", "0"],
                cwd=settings.BASE_DIR,
                env=env,
                text=True,
                capture_output=True,
                timeout=90,
            )
            self.assertEqual(migrate.returncode, 0, migrate.stderr)
            create_actor = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "shell",
                    "-c",
                    (
                        "from django.contrib.auth import get_user_model; "
                        "get_user_model().objects.create_superuser(username='process-admin')"
                    ),
                ],
                cwd=settings.BASE_DIR,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(create_actor.returncode, 0, create_actor.stderr)

            worker_code = "\n".join(
                [
                    "import copy, json",
                    "from django.contrib.auth import get_user_model",
                    "from django.core.exceptions import ValidationError",
                    "from apps.core.json_utils import load_json_file",
                    "from apps.settings_center.contract_services import apply_contract_payload",
                    "payload = load_json_file('contracts/role_rules.json')",
                    "role = next(key for key in payload if not key.startswith('$'))",
                    "payload[role]['display_name'] = __LABEL__",
                    "actor = get_user_model().objects.get(username='process-admin')",
                    "try:",
                    "    change = apply_contract_payload(actor=actor, setting_id='core.contract.role_rules', raw_payload=json.dumps(payload, ensure_ascii=False), confirmed=True, base_hash=__BASE_HASH__)",
                    "    print('WRITER_RESULT=applied:' + str(change.pk))",
                    "except ValidationError as exc:",
                    "    print('WRITER_RESULT=stale:' + str(exc))",
                ]
            )
            workers = []
            for label in ("Первый процесс", "Второй процесс"):
                code = worker_code.replace("__LABEL__", repr(label)).replace(
                    "__BASE_HASH__", repr(base_hash)
                )
                workers.append(
                    subprocess.Popen(
                        [sys.executable, "manage.py", "shell", "-c", code],
                        cwd=settings.BASE_DIR,
                        env=env,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )
            outputs = [worker.communicate(timeout=30) for worker in workers]
            for worker, (_stdout, stderr) in zip(workers, outputs, strict=True):
                self.assertEqual(worker.returncode, 0, stderr)
            result_lines = [
                line
                for stdout, _stderr in outputs
                for line in stdout.splitlines()
                if line.startswith("WRITER_RESULT=")
            ]
            self.assertEqual(sum("=applied:" in line for line in result_lines), 1)
            self.assertEqual(sum("=stale:" in line for line in result_lines), 1)

            with sqlite3.connect(database_file) as database:
                statuses = database.execute(
                    "SELECT status FROM settings_center_settingschange "
                    "WHERE setting_id = ? ORDER BY id",
                    ("core.contract.role_rules",),
                ).fetchall()
            self.assertEqual(statuses, [(SettingsChange.Status.APPLIED,)])
            written = load_json_file(role_file)
            self.assertTrue(
                any(
                    config.get("display_name") in {"Первый процесс", "Второй процесс"}
                    for role, config in written.items()
                    if not role.startswith("$")
                )
            )

    def test_write_failure_is_detectable_and_does_not_change_file(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ), patch(
                "apps.settings_center.contract_services.atomic_write_json",
                side_effect=OSError("fault before replace"),
            ):
                with self.assertRaises(OSError):
                    apply_contract_payload(
                        actor=self.actor,
                        setting_id="core.contract.role_rules",
                        raw_payload=json.dumps(self._changed("Сбой"), ensure_ascii=False),
                        confirmed=True,
                        base_hash=normalized_hash(self.payload),
                    )

            change = SettingsChange.objects.get(setting_id="core.contract.role_rules")
            self.assertEqual(change.status, SettingsChange.Status.FAILED)
            self.assertEqual(change.failure_code, "write_not_observed")
            self.assertEqual(load_json_file(role_file), self.payload)

    def test_reconcile_repairs_crash_after_replace_without_rewriting_file(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
            changed = self._changed("После replace")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                with patch(
                    "apps.settings_center.contract_services._finalize_contract_change",
                    side_effect=RuntimeError("fault after replace"),
                ):
                    with self.assertRaises(RuntimeError):
                        apply_contract_payload(
                            actor=self.actor,
                            setting_id="core.contract.role_rules",
                            raw_payload=json.dumps(changed, ensure_ascii=False),
                            confirmed=True,
                            base_hash=normalized_hash(self.payload),
                        )

                change = SettingsChange.objects.get(setting_id="core.contract.role_rules")
                self.assertEqual(change.status, SettingsChange.Status.PENDING)
                self.assertEqual(load_json_file(role_file), changed)
                dry_run = reconcile_pending_contract_changes(apply=False)
                change.refresh_from_db()
                self.assertEqual(dry_run[0]["classification"], "applied")
                self.assertEqual(change.status, SettingsChange.Status.PENDING)

                output = StringIO()
                call_command("reconcile_settings_changes", "--apply", stdout=output)
                change.refresh_from_db()
                self.assertEqual(change.status, SettingsChange.Status.APPLIED)
                self.assertIsNotNone(change.reconciled_at)
                self.assertNotIn("После replace", output.getvalue())
                self.assertEqual(reconcile_pending_contract_changes(apply=True), [])

    def test_inconsistent_file_blocks_next_apply(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
            planned = self._changed("План")
            change = SettingsChange.objects.create(
                actor=self.actor,
                setting_id="core.contract.role_rules",
                domain="core",
                storage_kind="runtime_contract",
                action=SettingsChange.Action.APPLY,
                status=SettingsChange.Status.PENDING,
                before_hash=normalized_hash(self.payload),
                after_hash=normalized_hash(planned),
                before_snapshot=self.payload,
                after_snapshot=planned,
                contract_relpath="role_rules.json",
            )
            divergent = self._changed("Неизвестная версия")
            role_file.write_text(json.dumps(divergent, ensure_ascii=False), encoding="utf-8")

            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                reports = reconcile_pending_contract_changes(apply=True)
                self.assertEqual(reports[0]["classification"], "divergent")
                change.refresh_from_db()
                self.assertEqual(change.status, SettingsChange.Status.INCONSISTENT)
                with self.assertRaisesMessage(ValidationError, "неизвестной версией"):
                    apply_contract_payload(
                        actor=self.actor,
                        setting_id="core.contract.role_rules",
                        raw_payload=json.dumps(self._changed("Новая попытка"), ensure_ascii=False),
                        confirmed=True,
                        base_hash=normalized_hash(divergent),
                    )

    def test_rollback_is_new_authorized_audited_change(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            role_file = root / "role_rules.json"
            role_file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                RUNTIME_CONTRACTS_DIR=root,
            ):
                source = apply_contract_payload(
                    actor=self.actor,
                    setting_id="core.contract.role_rules",
                    raw_payload=json.dumps(self._changed("Для отката"), ensure_ascii=False),
                    confirmed=True,
                    base_hash=normalized_hash(self.payload),
                )
                preview = preview_contract_rollback(actor=self.actor, change_id=source.pk)
                rollback = rollback_contract_change(
                    actor=self.actor,
                    change_id=source.pk,
                    confirmed=True,
                    base_hash=preview["base_hash"],
                )
                self.assertEqual(rollback.action, SettingsChange.Action.ROLLBACK)
                self.assertEqual(rollback.rollback_of_id, source.pk)
                self.assertEqual(load_json_file(role_file), self.payload)
                with self.assertRaisesMessage(ValidationError, "последнюю применённую"):
                    preview_contract_rollback(actor=self.actor, change_id=source.pk)

    def test_external_path_and_outer_transaction_are_rejected_before_write(self):
        with TemporaryDirectory() as tmpdir:
            external = Path(tmpdir) / "role_rules.json"
            external.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
            other_root = Path(tmpdir) / "runtime"
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=external,
                RUNTIME_CONTRACTS_DIR=other_root,
            ):
                with self.assertRaisesMessage(ValidationError, "только внутри data/contracts"):
                    apply_contract_payload(
                        actor=self.actor,
                        setting_id="core.contract.role_rules",
                        raw_payload=json.dumps(self._changed("Вне root"), ensure_ascii=False),
                        confirmed=True,
                        base_hash=normalized_hash(self.payload),
                    )

            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=external,
                RUNTIME_CONTRACTS_DIR=Path(tmpdir),
            ), transaction.atomic():
                with self.assertRaisesMessage(ValidationError, "внутри транзакции"):
                    apply_contract_payload(
                        actor=self.actor,
                        setting_id="core.contract.role_rules",
                        raw_payload=json.dumps(self._changed("В транзакции"), ensure_ascii=False),
                        confirmed=True,
                        base_hash=normalized_hash(self.payload),
                    )
            self.assertFalse(SettingsChange.objects.exists())
            self.assertEqual(load_json_file(external), self.payload)

    def test_settings_change_admin_cannot_mutate_audit(self):
        from django.contrib import admin

        from .admin import SettingsChangeAdmin

        model_admin = SettingsChangeAdmin(SettingsChange, admin.site)
        request = RequestFactory().get("/admin/settings_center/settingschange/")
        request.user = self.actor
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertIn("before_snapshot", model_admin.exclude)


class SettingsCenterEnvAndHelpTests(TestCase):
    def test_env_proposal_masks_secret_values_and_writes_under_data(self):
        actor = User.objects.create_superuser(username="settings-root", password="pass")
        with TemporaryDirectory() as tmpdir:
            proposal_dir = Path(tmpdir) / "proposals"
            with override_settings(SETTINGS_CENTER_ENV_PROPOSAL_DIR=proposal_dir, SETTINGS_CENTER_ENV_APPLY_MODE="proposal"):
                proposal = create_env_proposal(
                    actor=actor,
                    target_label="test-host",
                    changes={"OPENAI_API_KEY": "sk-test-secret"},
                )

            self.assertEqual(SettingsEnvProposal.objects.count(), 1)
            self.assertTrue(Path(proposal.file_path).is_file())
            self.assertEqual(proposal.masked_changes["OPENAI_API_KEY"], "***")
            self.assertNotIn("sk-test-secret", Path(proposal.file_path).read_text(encoding="utf-8"))

    def test_help_context_masks_sensitive_values(self):
        context = build_help_context(
            "settings_center.env.OPENAI_API_KEY",
            current_value={"api_key": "sk-test-secret"},
        )
        answer = answer_help_question(
            setting_id="settings_center.env.OPENAI_API_KEY",
            question="Где хранить ключ?",
            current_value={"api_key": "sk-test-secret"},
        )

        self.assertEqual(context["current_value_summary"]["api_key"], "***")
        self.assertNotIn("sk-test-secret", json.dumps(answer, ensure_ascii=False))


class SettingsCenterUserViewsTests(TestCase):
    def test_user_forms_require_real_department_and_hide_quarantine(self):
        from apps.accounts.department_policy import get_unassigned_user_department
        from apps.core.models import Department

        quarantine = get_unassigned_user_department()
        real_department = Department.objects.create(name="Реальное подразделение формы")
        create_form = PortalUserCreateForm(
            data={
                "username": "missing-department",
                "password": "",
                "first_name": "",
                "last_name": "",
                "email": "",
                "department": "",
                "is_active": "on",
            }
        )

        self.assertFalse(create_form.is_valid())
        self.assertIn("department", create_form.errors)
        choices = set(
            PortalUserCreateForm().fields["department"].queryset.values_list("pk", flat=True)
        )
        self.assertNotIn(quarantine.pk, choices)
        self.assertIn(real_department.pk, choices)
        self.assertTrue(PortalUserProfileUpdateForm().fields["department"].required)

    def test_superuser_can_create_disable_and_link_user(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="settings-root", password="pass")
        department = Department.objects.create(name="Подразделение нового пользователя")
        self.client.force_login(actor)

        response = self.client.post(
            reverse("settings_center:user_create"),
            {
                "username": "operator-1",
                "password": "pass",
                "first_name": "Operator",
                "last_name": "One",
                "email": "operator@example.test",
                "department": department.pk,
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="operator-1")
        self.assertFalse(user.groups.exists())
        self.assertEqual(
            response["Location"],
            f"{reverse('settings_center:user_edit', kwargs={'pk': user.pk})}?focus=assign#assign",
        )
        assignment_page = self.client.get(response["Location"])
        self.assertContains(assignment_page, 'id="assign"', html=False)
        self.assertContains(assignment_page, "Теперь назначьте ему роль")

        response = self.client.post(
            reverse("settings_center:user_ad_link", kwargs={"pk": user.pk}),
            {
                "provider": "active_directory",
                "subject_id": "S-1-5-21-test",
                "username": "operator-1",
                "upn": "operator-1@example.test",
                "distinguished_name": "CN=Operator One,DC=example,DC=test",
                "domain": "EXAMPLE",
                "sync_status": "verified",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(user.external_identities.get().subject_id, "S-1-5-21-test")

        response = self.client.post(reverse("settings_center:user_disable", kwargs={"pk": user.pk}))
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(SettingsChange.objects.filter(action=SettingsChange.Action.AD_LINK).count(), 1)

    def test_profile_change_and_audit_roll_back_together(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="atomic-profile-root")
        before_department = Department.objects.create(name="До атомарного изменения")
        after_department = Department.objects.create(name="После атомарного изменения")
        target = User.objects.create_user(
            username="atomic-profile-target",
            first_name="До",
            department=before_department,
        )
        self.client.force_login(actor)
        with patch(
            "apps.settings_center.views.record_settings_change",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            self.client.post(
                reverse("settings_center:user_profile_edit", args=[target.pk]),
                {
                    "username": target.username,
                    "first_name": "После",
                    "last_name": "",
                    "email": "",
                    "department": after_department.pk,
                    "is_active": "on",
                    "password": "",
                },
            )

        target.refresh_from_db()
        self.assertEqual(target.first_name, "До")
        self.assertEqual(target.department_id, before_department.pk)

    def test_ad_link_and_audit_roll_back_together(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="atomic-ad-root")
        department = Department.objects.create(name="Подразделение атомарной AD связи")
        target = User.objects.create_user(username="atomic-ad-target", department=department)
        self.client.force_login(actor)
        with patch(
            "apps.settings_center.views.record_settings_change",
            side_effect=RuntimeError("audit unavailable"),
        ), self.assertRaises(RuntimeError):
            self.client.post(
                reverse("settings_center:user_ad_link", args=[target.pk]),
                {
                    "provider": "active_directory",
                    "subject_id": "S-1-5-21-atomic",
                    "username": target.username,
                    "upn": "atomic@example.test",
                    "distinguished_name": "",
                    "domain": "EXAMPLE",
                    "sync_status": "manual",
                },
            )

        self.assertFalse(ExternalIdentity.objects.filter(user=target).exists())

    def test_profile_and_ad_audit_use_keyed_fingerprints_without_raw_principals(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="fingerprint-root")
        department = Department.objects.create(name="Fingerprint department")
        target = User.objects.create_user(
            username="fingerprint-before",
            email="before@example.test",
            department=department,
        )
        self.client.force_login(actor)
        profile_response = self.client.post(
            reverse("settings_center:user_profile_edit", args=[target.pk]),
            {
                "username": "fingerprint-after",
                "first_name": "",
                "last_name": "",
                "email": "after@example.test",
                "department": department.pk,
                "is_active": "on",
                "password": "",
            },
        )
        self.assertEqual(profile_response.status_code, 302)
        profile_audit = SettingsChange.objects.get(action=SettingsChange.Action.USER_UPDATE)
        serialized_profile = json.dumps(profile_audit.masked_diff, sort_keys=True)
        self.assertTrue(profile_audit.masked_diff["changed"])
        self.assertNotIn("fingerprint-before", serialized_profile)
        self.assertNotIn("fingerprint-after", serialized_profile)
        self.assertNotIn("before@example.test", serialized_profile)
        self.assertNotIn("after@example.test", serialized_profile)
        self.assertIn("key_version", serialized_profile)

        ad_response = self.client.post(
            reverse("settings_center:user_ad_link", args=[target.pk]),
            {
                "provider": "active_directory",
                "subject_id": "S-1-5-21-secret-principal",
                "username": "secret-ad-login",
                "upn": "secret-ad-login@example.test",
                "distinguished_name": "CN=Secret Principal,DC=example,DC=test",
                "domain": "EXAMPLE",
                "sync_status": "manual",
            },
        )
        self.assertEqual(ad_response.status_code, 302)
        ad_audit = SettingsChange.objects.get(action=SettingsChange.Action.AD_LINK)
        serialized_ad = json.dumps(ad_audit.masked_diff, sort_keys=True)
        self.assertTrue(ad_audit.masked_diff["changed"])
        for raw_value in (
            "S-1-5-21-secret-principal",
            "secret-ad-login",
            "secret-ad-login@example.test",
            "CN=Secret Principal,DC=example,DC=test",
            "EXAMPLE",
        ):
            self.assertNotIn(raw_value, serialized_ad)
        self.assertIn("key_version", serialized_ad)

    def test_user_list_searches_and_filters_on_the_server(self):
        from apps.core.models import Department

        manager_group, _ = Group.objects.get_or_create(name="manager")
        customer_group, _ = Group.objects.get_or_create(name="customer")
        actor = User.objects.create_user(username="access-filter-manager")
        actor.groups.add(manager_group)
        department = Department.objects.create(name="Фильтруемое подразделение")
        child_department = Department.objects.create(
            name="Дочернее фильтруемое подразделение",
            parent=department,
        )
        target = User.objects.create_user(
            username="access-filter-target",
            first_name="Ирина",
            last_name="Фильтрова",
            email="filter-target@example.test",
            department=child_department,
        )
        technical_group, _ = Group.objects.get_or_create(name="memory_observer")
        target.groups.add(customer_group, technical_group)
        ExternalIdentity.objects.create(
            user=target,
            subject_id="S-1-5-21-filter-target",
            username="ad-filter-target",
            upn="ad-filter-target@example.test",
            domain="EXAMPLE",
        )
        inactive_target = User.objects.create_user(
            username="access-filter-inactive",
            department=department,
            is_active=False,
        )
        inactive_target.groups.add(customer_group)
        self.client.force_login(actor)
        url = reverse("settings_center:user_list")

        for query in ("Ирина", "access-filter-target", "filter-target@example.test", "ad-filter-target"):
            with self.subTest(query=query):
                response = self.client.get(url, {"q": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [user.pk for user in response.context["portal_users"]], [target.pk]
                )

        role_response = self.client.get(url, {"role": "customer"})
        self.assertIn(target.pk, [user.pk for user in role_response.context["portal_users"]])
        self.assertNotIn(actor.pk, [user.pk for user in role_response.context["portal_users"]])

        department_response = self.client.get(url, {"department": department.pk})
        self.assertIn(target.pk, [user.pk for user in department_response.context["portal_users"]])
        self.assertNotIn(actor.pk, [user.pk for user in department_response.context["portal_users"]])

        attention_response = self.client.get(url, {"attention": "attention"})
        self.assertIn(inactive_target.pk, [user.pk for user in attention_response.context["portal_users"]])
        self.assertNotIn(target.pk, [user.pk for user in attention_response.context["portal_users"]])

    def test_user_list_keeps_filters_when_paginating_and_has_one_access_entrypoint(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        actor = User.objects.create_user(username="access-pagination-manager")
        actor.groups.add(manager_group)
        for number in range(51):
            User.objects.create_user(username=f"access-page-{number:02d}")
        self.client.force_login(actor)

        response = self.client.get(reverse("settings_center:user_list"), {"q": "access-page-"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])
        self.assertContains(response, "?q=access-page-&amp;page=2", html=False)
        self.assertContains(response, '<span class="nav-text">Доступ</span>', html=False)
        self.assertNotContains(response, '<span class="nav-text">Роли доступа</span>', html=False)

    def test_manage_roles_user_can_open_list_and_access_card_but_regular_user_cannot(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        manager = User.objects.create_user(username="role-manager")
        manager.groups.add(manager_group)
        regular = User.objects.create_user(username="role-regular")
        target = User.objects.create_user(username="role-target")

        self.client.force_login(regular)
        self.assertEqual(self.client.get(reverse("settings_center:user_list")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("settings_center:user_edit", kwargs={"pk": target.pk})).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("settings_center:user_edit", kwargs={"pk": 999999})).status_code,
            403,
        )

        self.client.force_login(manager)
        user_list_response = self.client.get(reverse("settings_center:user_list"))
        self.assertEqual(user_list_response.status_code, 200)
        self.assertContains(user_list_response, "Доступ сотрудников")
        response = self.client.get(reverse("settings_center:user_edit", kwargs={"pk": target.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Итоговый доступ и источники")
        self.assertEqual(
            self.client.get(
                reverse("settings_center:user_profile_edit", kwargs={"pk": target.pk})
            ).status_code,
            403,
        )

    def test_staff_only_and_inactive_superuser_cannot_open_access_administration(self):
        staff = User.objects.create_user(
            username="access-staff-only",
            is_staff=True,
        )
        inactive_root = User.objects.create_superuser(username="access-inactive-root")
        inactive_root.is_active = False
        inactive_root.save(update_fields=["is_active"])
        target = User.objects.create_user(username="inactive-access-target")

        for actor in (staff, inactive_root):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                self.assertIn(
                    self.client.get(reverse("settings_center:user_list")).status_code,
                    {302, 403},
                )
                self.assertIn(
                    self.client.get(
                        reverse("settings_center:user_edit", kwargs={"pk": target.pk})
                    ).status_code,
                    {302, 403},
                )

    def test_superuser_profile_update_preserves_roles_groups_and_technical_flags(self):
        from apps.core.models import Department

        actor = User.objects.create_superuser(username="profile-root", password="pass")
        target = User.objects.create_user(username="profile-user", first_name="До")
        department = Department.objects.create(name="Подразделение профиля")
        role, _ = Group.objects.get_or_create(name="customer")
        technical, _ = Group.objects.get_or_create(name="memory_observer")
        target.groups.add(role, technical)
        self.client.force_login(actor)

        response = self.client.post(
            reverse("settings_center:user_profile_edit", kwargs={"pk": target.pk}),
            {
                "username": "profile-user",
                "first_name": "После",
                "last_name": "",
                "email": "",
                "department": department.pk,
                "password": "",
                "is_active": "on",
                "is_staff": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertEqual(target.first_name, "После")
        self.assertEqual(target.department_id, department.pk)
        self.assertFalse(target.is_staff)
        self.assertEqual(
            set(target.groups.values_list("name", flat=True)),
            {"customer", "memory_observer"},
        )
        self.assertEqual(
            SettingsChange.objects.filter(action=SettingsChange.Action.USER_UPDATE).count(),
            1,
        )

    def test_access_card_preview_confirm_apply_preserves_technical_groups_and_flags(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        customer_group, _ = Group.objects.get_or_create(name="customer")
        technician_group, _ = Group.objects.get_or_create(name="technician")
        technical_group, _ = Group.objects.get_or_create(name="memory_observer")
        actor = User.objects.create_user(username="assignment-manager")
        actor.groups.add(manager_group)
        target = User.objects.create_user(username="assignment-target", is_staff=True)
        target.groups.add(customer_group, technical_group)
        self.client.force_login(actor)
        url = reverse("settings_center:user_edit", kwargs={"pk": target.pk})

        direct_apply = self.client.post(url, {"action": "apply", "roles": [technician_group.pk]})
        self.assertEqual(direct_apply.status_code, 200)
        self.assertContains(direct_apply, "Сначала выполните предпросмотр")
        self.assertEqual(set(target.groups.values_list("name", flat=True)), {"customer", "memory_observer"})

        response = self.client.post(url, {"action": "preview", "roles": [technician_group.pk]})
        self.assertEqual(response.status_code, 200)
        preview = response.context["preview"]
        self.assertTrue(preview["requires_confirmation"])

        response = self.client.post(
            url,
            {
                "action": "apply",
                "roles": [technician_group.pk],
                "preview_token": preview["preview_token"],
                "confirm_risk": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.is_staff)
        self.assertFalse(target.is_superuser)
        self.assertEqual(set(target.groups.values_list("name", flat=True)), {"technician", "memory_observer"})
        self.assertEqual(AccessAssignmentAudit.objects.filter(target_user=target).count(), 1)

    def test_superuser_access_card_changes_technical_flags_with_preview(self):
        actor = User.objects.create_superuser(username="assignment-root")
        target = User.objects.create_user(username="assignment-flags-target")
        self.client.force_login(actor)
        url = reverse("settings_center:user_edit", kwargs={"pk": target.pk})

        page = self.client.get(url)
        self.assertContains(page, "Супер-пользователь")
        self.assertContains(page, "Доступ к администрированию")

        preview_response = self.client.post(
            url,
            {
                "action": "preview",
                "is_staff": "on",
                "is_superuser": "on",
            },
        )
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.context["preview"]
        self.assertTrue(preview["requires_confirmation"])

        apply_response = self.client.post(
            url,
            {
                "action": "apply",
                "is_staff": "on",
                "is_superuser": "on",
                "preview_token": preview["preview_token"],
                "confirm_risk": "on",
            },
        )
        self.assertEqual(apply_response.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.is_staff)
        self.assertTrue(target.is_superuser)
        audit = AccessAssignmentAudit.objects.get(target_user=target)
        self.assertEqual({item["code"] for item in audit.flags_changed}, {"is_staff", "is_superuser"})

    def test_role_manager_does_not_see_technical_flag_controls(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        actor = User.objects.create_user(username="flags-role-manager")
        actor.groups.add(manager_group)
        target = User.objects.create_user(username="flags-readonly-target", is_staff=True)
        self.client.force_login(actor)

        response = self.client.get(reverse("settings_center:user_edit", kwargs={"pk": target.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="is_staff"', html=False)
        self.assertNotContains(response, 'name="is_superuser"', html=False)

    def test_role_manager_sees_own_and_privileged_target_roles_as_read_only(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        admin_group, _ = Group.objects.get_or_create(name="admin")
        customer_group, _ = Group.objects.get_or_create(name="customer")
        actor = User.objects.create_user(username="protected-role-manager")
        actor.groups.add(manager_group)
        privileged_target = User.objects.create_user(username="protected-role-target")
        privileged_target.groups.add(admin_group, customer_group)
        self.client.force_login(actor)

        own_response = self.client.get(
            reverse("settings_center:user_edit", kwargs={"pk": actor.pk})
        )
        target_response = self.client.get(
            reverse("settings_center:user_edit", kwargs={"pk": privileged_target.pk})
        )

        self.assertContains(own_response, "Сохраняются без изменения")
        self.assertNotContains(own_response, f'value="{manager_group.pk}"')
        self.assertContains(target_response, "Сохраняются без изменения")
        self.assertNotContains(target_response, f'value="{admin_group.pk}"')
        self.assertContains(target_response, f'value="{customer_group.pk}"')

    def test_profile_form_does_not_expose_privileged_flags(self):
        form = PortalUserProfileUpdateForm()

        self.assertNotIn("is_staff", form.fields)
        self.assertNotIn("is_superuser", form.fields)

    def test_memory_group_expert_view_is_superuser_only_and_uses_preview_apply(self):
        from apps.memory.models import MemoryGroupMembershipAudit

        root = User.objects.create_superuser(username="memory-expert-root")
        manager_group, _ = Group.objects.get_or_create(name="manager")
        manager = User.objects.create_user(username="memory-expert-manager")
        manager.groups.add(manager_group)
        target = User.objects.create_user(username="memory-expert-target")
        role, _ = Group.objects.get_or_create(name="customer")
        observer, _ = Group.objects.get_or_create(name="memory_observer")
        target.groups.add(role)
        url = reverse("settings_center:memory_group_membership", kwargs={"pk": target.pk})

        self.client.force_login(manager)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(root)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Экспертный сценарий памяти")
        preview_response = self.client.post(
            url,
            {
                "action": "preview",
                "group_names": [observer.name],
                "reason": "Назначение наблюдателя памяти.",
            },
        )
        preview = preview_response.context["preview"]
        apply_response = self.client.post(
            url,
            {
                "action": "apply",
                "group_names": [observer.name],
                "reason": "Назначение наблюдателя памяти.",
                "preview_token": preview["preview_token"],
                "confirmed": "on",
            },
        )

        self.assertEqual(apply_response.status_code, 302)
        self.assertEqual(
            set(target.groups.values_list("name", flat=True)),
            {"customer", "memory_observer"},
        )
        self.assertEqual(MemoryGroupMembershipAudit.objects.filter(target_user=target).count(), 1)


class SettingsCenterGroupProfileTests(TestCase):
    def test_role_field_label_uses_profile_title_and_description(self):
        group, _ = Group.objects.get_or_create(name="doctor")
        GroupProfile.objects.update_or_create(
            group=group,
            defaults={
                "title": "Врач",
                "description": "Приём пациентов, ведение карт, назначение лечения.",
            },
        )

        form = PortalUserUpdateForm()
        label = form.fields["roles"].label_from_instance(group)

        self.assertIn("Врач", label)
        self.assertIn("doctor", label)
        self.assertIn("Приём пациентов", label)

    def test_role_field_label_falls_back_to_name_without_profile(self):
        group, _ = Group.objects.get_or_create(name="customer")
        GroupProfile.objects.filter(group=group).delete()

        form = PortalUserUpdateForm()
        label = form.fields["roles"].label_from_instance(group)

        self.assertEqual(label, "customer")

    def test_user_access_page_shows_role_profile_and_keeps_technical_group_read_only(self):
        actor = User.objects.create_superuser(username="settings-root-groups", password="pass")
        group, _ = Group.objects.get_or_create(name="doctor")
        GroupProfile.objects.update_or_create(
            group=group,
            defaults={
                "title": "Врач",
                "description": "Работа с листом ожидания.",
            },
        )
        technical, _ = Group.objects.get_or_create(name="memory_auditor")
        target = User.objects.create_user(username="profile-target")
        target.groups.add(technical)
        self.client.force_login(actor)

        response = self.client.get(reverse("settings_center:user_edit", kwargs={"pk": target.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Врач")
        self.assertContains(response, "Работа с листом ожидания.")
        self.assertContains(response, "memory_auditor")
        self.assertNotContains(response, f'value="{technical.pk}"')
