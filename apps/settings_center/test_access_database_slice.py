"""Сквозные проверки PostgreSQL-среза настроек доступа."""

from __future__ import annotations

import copy
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.access_contracts import (
    role_definition_read_model,
    save_role_copy,
    save_role_creation,
    save_role_definition_change,
)
from apps.accounts.models import GroupProfile
from apps.accounts.selectors import default_new_user_role_name
from apps.core.contract_store import normalized_hash
from apps.core.json_utils import load_json_file
from apps.settings_center.contract_services import (
    apply_contract_payload,
    migrate_role_administration_metadata,
    migrate_role_capability_catalog,
    read_contract_snapshot,
    rollback_contract_change,
    save_default_new_user_role,
)
from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import (
    ConfigDocumentRepository,
    activate_repository,
    reset_repository,
)
from apps.settings_center.models import RuntimeSettingDocument, SettingsChange
from apps.settings_center.registry import get_registry
from apps.workorders.models import Board


pytestmark = [pytest.mark.integration, pytest.mark.serial]

ACCESS_DOCUMENT_IDS = (
    "core.contract.role_rules",
    "core.contract.workflow_rules",
    "workorders.contract.status_colors",
)


def clear_access_settings_caches():
    get_document_registry.cache_clear()
    get_registry.cache_clear()
    from apps.core import contract_store

    contract_store._reset_for_tests()


class AccessDatabaseAllowlistTests(SimpleTestCase):
    def tearDown(self):
        clear_access_settings_caches()
        super().tearDown()

    @override_settings(
        LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=("core.contract.role_rules",)
    )
    def test_partial_connected_slice_is_rejected(self):
        clear_access_settings_caches()
        with self.assertRaisesRegex(ValueError, "full connected slice"):
            get_document_registry()


@skipUnless(connection.vendor == "postgresql", "Требуется PostgreSQL")
@override_settings(LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=ACCESS_DOCUMENT_IDS)
class AccessDatabaseSliceTests(TransactionTestCase):
    """Проверить реальную связку доменного writer, БД, групп и аудита."""

    reset_sequences = True

    def setUp(self):
        super().setUp()
        clear_access_settings_caches()
        self.addCleanup(clear_access_settings_caches)
        self.actor = get_user_model().objects.create_superuser(
            username="access-document-owner",
            password="test-password",
        )

    @staticmethod
    def role_snapshot():
        return read_contract_snapshot(
            get_registry().get("core.contract.role_rules")
        )

    def test_access_administration_e2e_uses_database_backend_and_rolls_back(self):
        output = StringIO()

        call_command("access_administration_e2e", stdout=output)

        self.assertIn("access_administration_e2e: OK", output.getvalue())
        self.assertFalse(
            RuntimeSettingDocument.objects.filter(
                document_id="core.contract.role_rules"
            ).exists()
        )
        self.assertFalse(
            get_user_model().objects.filter(
                username__startswith="e2e_access_admin_"
            ).exists()
        )
        self.assertFalse(
            Group.objects.filter(name__startswith="e2e_access_").exists()
        )
        self.assertFalse(SettingsChange.objects.exists())

    def test_create_and_copy_roles_materialize_inert_groups_atomically(self):
        before = self.role_snapshot()
        created = save_role_creation(
            actor=self.actor,
            role_code="db_operator",
            display_name="Оператор БД",
            description="Создан сквозной проверкой",
            base_hash=before.content_hash,
            base_revision=before.revision,
        )
        after_create = self.role_snapshot()
        copied = save_role_copy(
            actor=self.actor,
            source_role_code="db_operator",
            target_role_code="db_operator_copy",
            display_name="Копия оператора БД",
            description="Плоская копия без назначений",
            base_hash=after_create.content_hash,
            base_revision=after_create.revision,
        )

        row = RuntimeSettingDocument.objects.get(
            document_id="core.contract.role_rules"
        )
        self.assertEqual(row.revision, 2)
        self.assertIn("db_operator", row.payload)
        self.assertIn("db_operator_copy", row.payload)
        self.assertEqual(
            row.payload["db_operator_copy"]["display_name"],
            "Копия оператора БД",
        )
        for role_code in ("db_operator", "db_operator_copy"):
            group = Group.objects.get(name=role_code)
            profile = GroupProfile.objects.get(group=group)
            self.assertTrue(profile.is_predefined)
            self.assertFalse(group.user_set.exists())
            self.assertFalse(group.permissions.exists())
            self.assertFalse(Board.objects.filter(allowed_groups=group).exists())
        self.assertEqual(created.document_revision_after, 1)
        self.assertEqual(copied.document_revision_after, 2)

    def test_repeated_role_creation_repairs_missing_group_without_new_revision_or_audit(self):
        from apps.accounts.access_contracts import _new_role_config

        before = self.role_snapshot()
        role_code = "db_repair_role"
        display_name = "Восстанавливаемая роль"
        description = "Роль уже есть в документе"
        payload = copy.deepcopy(before.payload)
        payload[role_code] = _new_role_config(
            role_code=role_code,
            display_name=display_name,
            description=description,
            protected=False,
            catalog=payload["$capabilities"],
        )
        row = RuntimeSettingDocument.objects.create(
            document_id="core.contract.role_rules",
            schema_version=before.schema_version,
            payload=payload,
            revision=7,
            content_hash=document_hash(payload),
            default_hash=before.default_hash,
            updated_by=self.actor,
        )
        expected_revision = row.revision
        expected_hash = row.content_hash
        expected_payload = copy.deepcopy(row.payload)
        audit_count = SettingsChange.objects.filter(
            setting_id="core.contract.role_rules"
        ).count()

        result = save_role_creation(
            actor=self.actor,
            role_code=role_code,
            display_name=display_name,
            description=description,
            protected=False,
            base_hash=expected_hash,
            base_revision=expected_revision,
        )

        self.assertIsNone(result)
        row.refresh_from_db()
        self.assertEqual(row.revision, expected_revision)
        self.assertEqual(row.content_hash, expected_hash)
        self.assertEqual(row.payload, expected_payload)
        self.assertEqual(
            SettingsChange.objects.filter(
                setting_id="core.contract.role_rules"
            ).count(),
            audit_count,
        )
        group = Group.objects.get(name=role_code)
        profile = GroupProfile.objects.get(group=group)
        self.assertTrue(profile.is_predefined)
        self.assertEqual(profile.title, display_name)
        self.assertEqual(profile.description, description)

    def test_access_workspace_creates_role_and_renders_new_database_revision(self):
        self.client.force_login(self.actor)
        url = reverse("settings_center:access_workspace")
        opened = self.client.get(
            url,
            {"view": "roles", "create": "role", "panel": "inspector"},
        )
        form = opened.context["field_form"]

        response = self.client.post(
            url,
            {
                "view": "roles",
                "create": "role",
                "field": "definition",
                "panel": "inspector",
                "action": "create_role",
                "code": "http_db_role",
                "display_name": "Роль из HTTP",
                "description": "Сквозной сценарий интерфейса",
                "base_hash": form["base_hash"].value(),
                "base_revision": form["base_revision"].value(),
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="global-right-panel-content",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "http_db_role")
        row = RuntimeSettingDocument.objects.get(
            document_id="core.contract.role_rules"
        )
        self.assertEqual(row.revision, 1)
        self.assertIn("http_db_role", row.payload)

    def test_workflow_matrix_http_write_uses_database_cas(self):
        self.client.force_login(self.actor)
        url = reverse("settings_center:workflow_transitions")
        opened = self.client.get(url)

        response = self.client.post(
            url,
            {
                "action": "deny_all",
                "confirm": "on",
                "base_hash": opened.context["base_hash"],
                "base_revision": opened.context["base_revision"],
            },
        )

        self.assertEqual(response.status_code, 302)
        row = RuntimeSettingDocument.objects.get(
            document_id="core.contract.workflow_rules"
        )
        self.assertEqual(row.revision, 1)
        self.assertTrue(
            all(not targets for targets in row.payload["transitions"].values())
        )

    def test_group_reservation_rolls_back_when_audit_write_fails(self):
        before = self.role_snapshot()
        with patch.object(
            SettingsChange.objects,
            "create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                save_role_creation(
                    actor=self.actor,
                    role_code="rolled_back_role",
                    display_name="Откатываемая роль",
                    base_hash=before.content_hash,
                    base_revision=before.revision,
                )

        self.assertFalse(Group.objects.filter(name="rolled_back_role").exists())
        self.assertFalse(
            RuntimeSettingDocument.objects.filter(
                document_id="core.contract.role_rules"
            ).exists()
        )

    def test_delegated_role_editor_does_not_need_manage_settings(self):
        manager = Group.objects.create(name="manager")
        editor = get_user_model().objects.create_user(username="delegated-role-editor")
        editor.groups.add(manager)
        model = role_definition_read_model("customer")
        proposed = copy.deepcopy(model["config"])
        proposed["description"] = "Изменено делегированным редактором"

        change = save_role_definition_change(
            actor=editor,
            role_code="customer",
            proposed_config=proposed,
            base_hash=model["base_hash"],
            base_revision=model["base_revision"],
        )

        self.assertEqual(change.document_revision_after, 1)
        self.assertEqual(
            self.role_snapshot().payload["customer"]["description"],
            "Изменено делегированным редактором",
        )

    def test_default_role_uses_database_revision_and_selector_reads_it(self):
        Group.objects.create(name="customer")
        repository = ConfigDocumentRepository()
        token = activate_repository(repository)
        try:
            before = self.role_snapshot()
            change = save_default_new_user_role(
                actor=self.actor,
                role_name="customer",
                base_hash=before.content_hash,
                base_revision=before.revision,
                reason="Роль для новых сотрудников",
            )
            # Writer обязан удалить старый request-local снимок: следующий
            # потребитель в том же запросе уже видит новую ревизию.
            selected_role = default_new_user_role_name()
        finally:
            reset_repository(token)

        self.assertEqual(change.document_revision_after, 1)
        self.assertEqual(selected_role, "customer")

    def test_ordinary_apply_and_rollback_cannot_change_frozen_catalog(self):
        before = self.role_snapshot()
        changed_catalog = copy.deepcopy(before.payload)
        changed_catalog["$capabilities"]["view_scope"]["label"] += " (подмена)"

        with self.assertRaisesMessage(ValidationError, "$capabilities"):
            apply_contract_payload(
                actor=self.actor,
                setting_id="core.contract.role_rules",
                raw_payload=json.dumps(changed_catalog, ensure_ascii=False),
                confirmed=True,
                base_hash=before.content_hash,
                base_revision=before.revision,
            )

        source = SettingsChange.objects.create(
            actor=self.actor,
            setting_id="core.contract.role_rules",
            domain="accounts",
            storage_kind="runtime_document",
            action=SettingsChange.Action.APPLY,
            status=SettingsChange.Status.APPLIED,
            before_hash=document_hash(changed_catalog),
            after_hash=before.content_hash,
            before_snapshot=changed_catalog,
            after_snapshot=before.payload,
            document_revision_after=before.revision or None,
        )
        with self.assertRaisesMessage(ValidationError, "$capabilities"):
            rollback_contract_change(
                actor=self.actor,
                change_id=source.pk,
                confirmed=True,
                base_hash=before.content_hash,
                base_revision=before.revision,
            )
        self.assertFalse(RuntimeSettingDocument.objects.exists())

    def test_workflow_write_validates_complete_connected_slice(self):
        descriptor = get_registry().get("core.contract.workflow_rules")
        before = read_contract_snapshot(descriptor)
        candidate = copy.deepcopy(before.payload)
        candidate["statuses"].append("uncoloured_test_status")
        candidate["transitions"]["uncoloured_test_status"] = []

        with self.assertRaises(ValidationError):
            apply_contract_payload(
                actor=self.actor,
                setting_id=descriptor.setting_id,
                raw_payload=json.dumps(candidate, ensure_ascii=False),
                confirmed=True,
                base_hash=before.content_hash,
                base_revision=before.revision,
            )

        self.assertFalse(RuntimeSettingDocument.objects.exists())

    def test_deployment_catalog_migration_updates_payload_and_default_hash(self):
        git_payload = copy.deepcopy(self.role_snapshot().payload)
        runtime_payload = copy.deepcopy(git_payload)
        runtime_payload["$capabilities"]["view_scope"]["label"] += " (старый)"
        RuntimeSettingDocument.objects.create(
            document_id="core.contract.role_rules",
            schema_version=1,
            payload=runtime_payload,
            revision=1,
            content_hash=document_hash(runtime_payload),
            default_hash="0" * 64,
            updated_by=self.actor,
        )
        with TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "contracts"
            runtime_root.mkdir()
            with override_settings(
                DATA_DIR=Path(directory),
                RUNTIME_CONTRACTS_DIR=runtime_root,
            ):
                result = migrate_role_capability_catalog(
                    actor=self.actor,
                    candidate_path=Path(settings.BASE_DIR)
                    / "contracts"
                    / "role_rules.json",
                    expected_runtime_catalog_hash=normalized_hash(
                        runtime_payload["$capabilities"]
                    ),
                    expected_git_catalog_hash=normalized_hash(
                        git_payload["$capabilities"]
                    ),
                    expected_runtime_hash=normalized_hash(runtime_payload),
                    reason="Проверка DB deployment writer",
                )

        row = RuntimeSettingDocument.objects.get(
            document_id="core.contract.role_rules"
        )
        self.assertEqual(row.payload, git_payload)
        self.assertEqual(row.revision, 2)
        self.assertEqual(row.default_hash, document_hash(git_payload))
        self.assertEqual(result["change"].document_revision_after, 2)
        self.assertEqual(
            result["change"].validation_result["operation"],
            "deployment_role_capability_catalog_migration",
        )

    def _administration_runtime(self):
        git_payload = copy.deepcopy(self.role_snapshot().payload)
        runtime_payload = copy.deepcopy(git_payload)
        runtime_payload["$administration"] = {
            "role_definition_editor_roles": ["admin"],
            "role_assignment_allowlist": {"manager": ["customer"]},
        }
        RuntimeSettingDocument.objects.create(
            document_id="core.contract.role_rules",
            schema_version=1,
            payload=runtime_payload,
            revision=1,
            content_hash=document_hash(runtime_payload),
            default_hash=document_hash(git_payload),
            updated_by=self.actor,
        )
        return git_payload, runtime_payload

    def test_administration_deployment_writer_removes_only_block_and_audits(self):
        git_payload, runtime_payload = self._administration_runtime()
        with TemporaryDirectory() as directory:
            with override_settings(DATA_DIR=Path(directory)):
                result = migrate_role_administration_metadata(
                    actor=self.actor,
                    expected_runtime_hash=normalized_hash(runtime_payload),
                    expected_git_hash=normalized_hash(git_payload),
                    reason="Проверка миграции administration",
                )
                backup_path = result["backup_path"]
                self.assertTrue(backup_path.exists())
                self.assertEqual(load_json_file(backup_path), runtime_payload)
        current = RuntimeSettingDocument.objects.get(
            document_id="core.contract.role_rules"
        )
        expected = copy.deepcopy(runtime_payload)
        expected.pop("$administration")
        self.assertEqual(current.payload, expected)
        self.assertEqual(current.revision, 2)
        self.assertEqual(
            result["change"].validation_result["operation"],
            "deployment_remove_role_administration",
        )

    def test_administration_deployment_hash_mismatch_is_no_write(self):
        git_payload, runtime_payload = self._administration_runtime()
        with TemporaryDirectory() as directory:
            with override_settings(DATA_DIR=Path(directory)):
                with self.assertRaises(ValidationError):
                    migrate_role_administration_metadata(
                        actor=self.actor,
                        expected_runtime_hash="0" * 64,
                        expected_git_hash=normalized_hash(git_payload),
                        reason="Неверный снимок",
                    )
                self.assertFalse(SettingsChange.objects.exists())
                backup_root = Path(directory) / "contracts" / "backups"
                self.assertTrue(
                    not backup_root.exists() or not any(backup_root.iterdir())
                )
        self.assertEqual(
            RuntimeSettingDocument.objects.get(
                document_id="core.contract.role_rules"
            ).payload,
            runtime_payload,
        )

    def test_administration_deployment_audit_failure_rolls_back_row_and_backup(self):
        git_payload, runtime_payload = self._administration_runtime()
        with TemporaryDirectory() as directory:
            with override_settings(DATA_DIR=Path(directory)):
                with patch.object(
                    SettingsChange.objects,
                    "create",
                    side_effect=RuntimeError("audit unavailable"),
                ):
                    with self.assertRaises(RuntimeError):
                        migrate_role_administration_metadata(
                            actor=self.actor,
                            expected_runtime_hash=normalized_hash(runtime_payload),
                            expected_git_hash=normalized_hash(git_payload),
                            reason="Проверка отката аудита",
                        )
                backup_root = Path(directory) / "contracts" / "backups"
                self.assertTrue(
                    not backup_root.exists() or not any(backup_root.iterdir())
                )
        current = RuntimeSettingDocument.objects.get(
            document_id="core.contract.role_rules"
        )
        self.assertEqual(current.revision, 1)
        self.assertEqual(current.payload, runtime_payload)
        self.assertFalse(SettingsChange.objects.exists())
