import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import AccessAssignmentAudit, GroupProfile
from apps.core.contract_store import get_contract, normalized_hash
from apps.core.json_utils import load_json_file

from .contract_services import apply_contract_payload
from .env_services import create_env_proposal
from .forms import PortalUserCreateForm, PortalUserProfileUpdateForm, PortalUserUpdateForm
from .help_services import answer_help_question, build_help_context
from .models import SettingsChange, SettingsEnvProposal
from .registry import get_registry


User = get_user_model()
pytestmark = pytest.mark.integration


class SettingsCenterRegistryTests(TestCase):
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

        self.assertRedirects(response, reverse("core:role_rules"), fetch_redirect_response=False)
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


class SettingsCenterContractTests(TestCase):
    def test_runtime_contract_apply_validates_writes_atomically_and_audits(self):
        actor = User.objects.create_user(username="settings-admin", password="pass", is_staff=True)
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
            ):
                change = apply_contract_payload(
                    actor=actor,
                    setting_id="core.contract.role_rules",
                    raw_payload=json.dumps(changed_payload, ensure_ascii=False),
                    confirmed=True,
                )

            self.assertEqual(change.status, SettingsChange.Status.APPLIED)
            self.assertTrue(change.masked_diff["changed"])
            self.assertEqual(load_json_file(role_file)[first_role]["display_name"], "Changed role name")

    def test_apply_with_stale_base_hash_is_rejected(self):
        from apps.core.contract_store import _reset_for_tests

        actor = User.objects.create_user(username="stale-admin", password="pass", is_staff=True)
        with TemporaryDirectory() as tmpdir:
            role_file = Path(tmpdir) / "role_rules.json"
            payload = load_json_file("contracts/role_rules.json")
            role_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            first_role = next(role for role in payload if not role.startswith("$"))

            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file):
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

    def test_workflow_transition_matrix_view_can_allow_all_transitions(self):
        actor = User.objects.create_user(username="workflow-admin", password="pass", is_staff=True)
        payload = {
            "statuses": ["new", "accepted", "closed"],
            "transitions": {
                "new": ["accepted"],
                "accepted": [],
                "closed": [],
            },
        }
        with TemporaryDirectory() as tmpdir:
            workflow_file = Path(tmpdir) / "workflow_rules.json"
            workflow_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_WORKFLOW_RULES_FILE=workflow_file,
                LOCAL_BUSINESS_WORKFLOW_RULES=payload,
            ):
                self.client.force_login(actor)
                response = self.client.get(reverse("settings_center:workflow_transitions"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Переходы статусов")

                response = self.client.post(
                    reverse("settings_center:workflow_transitions"),
                    {"action": "allow_all", "confirm": "on"},
                )

                self.assertEqual(response.status_code, 302)
                saved = load_json_file(workflow_file)
                self.assertEqual(set(saved["transitions"]["new"]), {"accepted", "closed"})
                self.assertEqual(set(saved["transitions"]["accepted"]), {"new", "closed"})
                self.assertEqual(set(saved["transitions"]["closed"]), {"new", "accepted"})
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
            ):
                self.client.force_login(actor)
                response = self.client.get(reverse("settings_center:workorder_status_colors"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Цвета статусов заявок")

                post_data = {"confirm": "on"}
                for status, config in payload["statuses"].items():
                    post_data[f"color__{status}"] = "#111111" if status == "new" else config["color"]
                    post_data[f"background__{status}"] = config["background"]

                response = self.client.post(reverse("settings_center:workorder_status_colors"), post_data)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(load_json_file(color_file)["statuses"]["new"]["color"], "#111111")


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
        self.assertContains(user_list_response, "Роли доступа")
        response = self.client.get(reverse("settings_center:user_edit", kwargs={"pk": target.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Итоговый доступ и источники")
        self.assertEqual(
            self.client.get(
                reverse("settings_center:user_profile_edit", kwargs={"pk": target.pk})
            ).status_code,
            403,
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
        technical_group, _ = Group.objects.get_or_create(name="memory_observer")
        actor = User.objects.create_user(username="assignment-manager")
        actor.groups.add(manager_group)
        target = User.objects.create_user(username="assignment-target", is_staff=True)
        target.groups.add(customer_group, technical_group)
        self.client.force_login(actor)
        url = reverse("settings_center:user_edit", kwargs={"pk": target.pk})

        direct_apply = self.client.post(url, {"action": "apply", "roles": [manager_group.pk]})
        self.assertEqual(direct_apply.status_code, 200)
        self.assertContains(direct_apply, "Сначала выполните предпросмотр")
        self.assertEqual(set(target.groups.values_list("name", flat=True)), {"customer", "memory_observer"})

        response = self.client.post(url, {"action": "preview", "roles": [manager_group.pk]})
        self.assertEqual(response.status_code, 200)
        preview = response.context["preview"]
        self.assertTrue(preview["requires_confirmation"])

        response = self.client.post(
            url,
            {
                "action": "apply",
                "roles": [manager_group.pk],
                "preview_token": preview["preview_token"],
                "confirm_risk": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.is_staff)
        self.assertFalse(target.is_superuser)
        self.assertEqual(set(target.groups.values_list("name", flat=True)), {"manager", "memory_observer"})
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

    def test_role_manager_sees_read_only_technical_flags(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        actor = User.objects.create_user(username="flags-role-manager")
        actor.groups.add(manager_group)
        target = User.objects.create_user(username="flags-readonly-target", is_staff=True)
        self.client.force_login(actor)

        response = self.client.get(reverse("settings_center:user_edit", kwargs={"pk": target.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="is_staff"', html=False)
        self.assertContains(response, "disabled", html=False)
        self.assertContains(response, "только супер-пользователю")

    def test_profile_form_does_not_expose_privileged_flags(self):
        form = PortalUserProfileUpdateForm()

        self.assertNotIn("is_staff", form.fields)
        self.assertNotIn("is_superuser", form.fields)


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
