import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.json_utils import load_json_file

from .contract_services import apply_contract_payload
from .env_services import create_env_proposal
from .help_services import answer_help_question, build_help_context
from .models import SettingsChange, SettingsEnvProposal
from .registry import get_registry


User = get_user_model()


class SettingsCenterRegistryTests(TestCase):
    def test_registry_loads_domain_descriptors(self):
        registry = get_registry()
        setting_ids = {descriptor.setting_id for descriptor in registry.all()}

        self.assertIn("core.contract.role_rules", setting_ids)
        self.assertIn("accounts.user.ad_identity_link", setting_ids)
        self.assertIn("ai.contract.tools", setting_ids)
        self.assertIn("memory.source.acl_mode", setting_ids)
        self.assertIn("settings_center.env.OPENAI_API_KEY", setting_ids)

    def test_dashboard_requires_staff(self):
        staff = User.objects.create_user(username="settings-staff", password="pass", is_staff=True)
        regular = User.objects.create_user(username="settings-regular", password="pass")

        self.client.force_login(regular)
        self.assertEqual(self.client.get(reverse("settings_center:dashboard")).status_code, 403)

        self.client.force_login(staff)
        response = self.client.get(reverse("settings_center:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Settings Center")

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
            first_role = next(role for role in changed_payload if role != "$schema")
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
                self.assertEqual(settings.LOCAL_BUSINESS_WORKFLOW_RULES, saved)
                self.assertEqual(SettingsChange.objects.filter(setting_id="core.contract.workflow_rules").count(), 1)


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
    def test_superuser_can_create_disable_and_link_user(self):
        actor = User.objects.create_superuser(username="settings-root", password="pass")
        group = Group.objects.create(name="operators")
        self.client.force_login(actor)

        response = self.client.post(
            reverse("settings_center:user_create"),
            {
                "username": "operator-1",
                "password": "pass",
                "first_name": "Operator",
                "last_name": "One",
                "email": "operator@example.test",
                "is_active": "on",
                "groups": [group.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="operator-1")
        self.assertIn(group, user.groups.all())

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
