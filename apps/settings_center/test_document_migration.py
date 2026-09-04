from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.contract_store import normalized_hash

from .document_hashes import document_hash
from .document_migration import (
    ALREADY_IMPORTED,
    AMBIGUOUS_DRIFT,
    AUDITED_OVERRIDE,
    CONFLICT,
    IDENTICAL_DEFAULT,
    MIGRATION_REQUIRED,
    MISSING_RUNTIME,
    SECURITY_REVIEW_REQUIRED,
    MigrationError,
    MigrationSliceError,
    UnsafeMigrationPath,
    UnsupportedMigrationBackend,
    UnsupportedMigrationPlatform,
    _backup_document,
    _atomic_write,
    _windows_target_has_reparse_point,
    apply_migration,
    classify_document,
    export_document,
    plan_migration,
)
from .document_registry import ConfigDocumentRegistry
from .document_security import classify_secret_references
from .document_specs import ConfigDocumentSpec
from .models import RuntimeSettingDocument, SettingsChange


@pytest.mark.integration
class DocumentMigrationTests(TestCase):
    """Проверки planner на изолированных temp contracts, не на data/contracts."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.contracts = self.root / "contracts"
        self.runtime = self.root / "data" / "contracts"
        self.contracts.mkdir()
        self.runtime.mkdir(parents=True)
        self.default_payload = {"enabled": True, "label": "default"}
        self.runtime_payload = {"enabled": True, "label": "operator"}
        self.default_file = self.contracts / "test.json"
        self.runtime_file = self.runtime / "test.json"
        self.default_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        self.runtime_file.write_text(json.dumps(self.runtime_payload), encoding="utf-8")
        self.spec = ConfigDocumentSpec(
            "test.contract.document",
            "test",
            "database_override",
            "contracts/test.json",
            1,
            lambda payload: None,
            "fail_closed",
            "editable",
            "manage_settings",
            "test",
        )
        self.override = override_settings(
            BASE_DIR=self.root,
            RUNTIME_CONTRACTS_DIR=self.runtime,
        )
        self.override.enable()
        self.registry = ConfigDocumentRegistry((self.spec,))

    def tearDown(self):
        self.override.disable()
        self.temp.cleanup()

    def _audit_legacy_write(self, payload=None):
        payload = payload or self.runtime_payload
        SettingsChange.objects.create(
            setting_id=self.spec.document_id,
            domain=self.spec.domain,
            storage_kind="runtime_contract",
            action=SettingsChange.Action.APPLY,
            status=SettingsChange.Status.APPLIED,
            before_hash=normalized_hash(self.default_payload),
            after_hash=normalized_hash(payload),
            before_snapshot=self.default_payload,
            after_snapshot=payload,
        )

    def test_identical_default_is_read_only_and_does_not_create_row(self):
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, IDENTICAL_DEFAULT)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)

    def test_missing_runtime_is_not_imported(self):
        self.runtime_file.unlink()

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, MISSING_RUNTIME)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)

    def test_runtime_without_latest_matching_audit_is_ambiguous(self):
        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, AMBIGUOUS_DRIFT)
        self.assertFalse(entry.audit_evidence)

    def test_only_latest_legacy_normalized_hash_is_evidence(self):
        self._audit_legacy_write()

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, AUDITED_OVERRIDE)
        self.assertTrue(entry.audit_evidence)
        self.assertEqual(entry.runtime_hash, normalized_hash(self.runtime_payload))
        self.assertNotEqual(entry.runtime_hash, document_hash(self.runtime_payload))

    def test_newer_mismatching_applied_audit_removes_legacy_evidence(self):
        self._audit_legacy_write()
        newer = {"enabled": True, "label": "newer-audit-version"}
        SettingsChange.objects.create(
            setting_id=self.spec.document_id,
            domain=self.spec.domain,
            storage_kind="runtime_contract",
            action=SettingsChange.Action.APPLY,
            status=SettingsChange.Status.APPLIED,
            before_hash=normalized_hash(self.default_payload),
            after_hash=normalized_hash(newer),
            before_snapshot=self.default_payload,
            after_snapshot=newer,
            applied_at=timezone.now() + timedelta(seconds=1),
        )

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, AMBIGUOUS_DRIFT)
        self.assertFalse(entry.audit_evidence)

    def test_audit_for_wrong_setting_id_is_not_evidence(self):
        SettingsChange.objects.create(
            setting_id="test.contract.other-document",
            domain=self.spec.domain,
            storage_kind="runtime_contract",
            action=SettingsChange.Action.APPLY,
            status=SettingsChange.Status.APPLIED,
            before_hash=normalized_hash(self.default_payload),
            after_hash=normalized_hash(self.runtime_payload),
            before_snapshot=self.default_payload,
            after_snapshot=self.runtime_payload,
        )

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, AMBIGUOUS_DRIFT)
        self.assertIsNone(entry.audit_change_id)

    def test_applied_rollback_hash_is_valid_legacy_evidence(self):
        SettingsChange.objects.create(
            setting_id=self.spec.document_id,
            domain=self.spec.domain,
            storage_kind="runtime_contract",
            action=SettingsChange.Action.ROLLBACK,
            status=SettingsChange.Status.APPLIED,
            before_hash=normalized_hash(self.default_payload),
            after_hash=normalized_hash(self.runtime_payload),
            before_snapshot=self.default_payload,
            after_snapshot=self.runtime_payload,
            applied_at=timezone.now(),
        )

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, AUDITED_OVERRIDE)
        self.assertTrue(entry.audit_evidence)

    def test_malformed_runtime_json_is_migration_required_without_payload(self):
        self.runtime_file.write_text("{ not-json ", encoding="utf-8")

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, MIGRATION_REQUIRED)
        self.assertNotIn("not-json", entry.reason)

    def test_malformed_legacy_runtime_is_conflict_even_with_healthy_db_row(self):
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=self.default_payload,
            revision=1,
            content_hash=document_hash(self.default_payload),
            default_hash=document_hash(self.default_payload),
        )
        self.runtime_file.write_text("{ broken-json", encoding="utf-8")

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, CONFLICT)
        self.assertNotIn("broken-json", entry.reason)

    def test_top_level_schema_marker_mismatch_is_migration_required(self):
        default = {"schema_version": 1, "enabled": True}
        runtime = {"schema_version": 2, "enabled": True}
        self.default_file.write_text(json.dumps(default), encoding="utf-8")
        self.runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
        SettingsChange.objects.create(
            setting_id=self.spec.document_id,
            domain=self.spec.domain,
            storage_kind="runtime_contract",
            action=SettingsChange.Action.APPLY,
            status=SettingsChange.Status.APPLIED,
            before_hash=normalized_hash(default),
            after_hash=normalized_hash(runtime),
            before_snapshot=default,
            after_snapshot=runtime,
        )

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, MIGRATION_REQUIRED)
        self.assertIn("schema marker", entry.reason)
        # The wrapper spec schema_version remains independent from the payload
        # marker and is not overwritten by the runtime value.
        self.assertEqual(entry.schema_version, self.spec.schema_version)

    def test_raw_secret_gate_covers_default_runtime_and_db_row(self):
        secret_value = "do-not-disclose-secret-value"

        self.default_file.write_text(
            json.dumps({"api_key": secret_value}), encoding="utf-8"
        )
        entry = classify_document(self.spec, registry=self.registry)
        self.assertEqual(entry.classification, CONFLICT)
        self.assertNotIn(secret_value, entry.reason)

        safe_default = {"enabled": True, "label": "default"}
        raw_runtime = {"token": secret_value}
        self.default_file.write_text(json.dumps(safe_default), encoding="utf-8")
        self.runtime_file.write_text(json.dumps(raw_runtime), encoding="utf-8")
        entry = classify_document(self.spec, registry=self.registry)
        self.assertEqual(entry.classification, CONFLICT)
        self.assertNotIn(secret_value, entry.reason)

        self.runtime_file.write_text(json.dumps(safe_default), encoding="utf-8")
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload={"secret": secret_value},
            revision=1,
            content_hash=document_hash({"secret": secret_value}),
            default_hash=document_hash(safe_default),
        )
        entry = classify_document(self.spec, registry=self.registry)
        self.assertEqual(entry.classification, CONFLICT)
        self.assertIn("db_raw_secret", entry.reason)
        self.assertNotIn(secret_value, entry.reason)

    def test_secret_key_normalization_rejects_common_variants(self):
        for key in (
            "apiKey",
            "api-key",
            "APIKey",
            "CLIENTSECRET",
            "ACCESSTOKEN",
            "secretKey",
            "tokenKey",
            "privateKey",
            "accessToken",
            "refreshToken",
            "clientSecret",
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    classify_secret_references({key: "sensitive"}), "rejected"
                )
        self.assertEqual(
            classify_secret_references({"secret": {"value": "sensitive"}}),
            "rejected",
        )
        self.assertEqual(
            classify_secret_references({"secret": {"key": "sensitive"}}),
            "rejected",
        )
        self.assertEqual(
            classify_secret_references({"token": {"key": "sensitive"}}),
            "rejected",
        )
        self.assertEqual(
            classify_secret_references({"secret": {"ref": "vault/item"}}),
            "reference_only",
        )
        self.assertEqual(
            classify_secret_references({"apiKeyRef": "vault/item"}),
            "reference_only",
        )
        self.assertEqual(
            classify_secret_references({"APIKEYREF": "vault/item"}),
            "reference_only",
        )
        self.assertEqual(
            classify_secret_references({"token_budget": 4096}),
            "clear",
        )

    def test_backup_secret_gate_never_writes_raw_payload(self):
        secret_value = "backup-secret-value"
        with TemporaryDirectory() as backup_directory:
            self.default_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
            entry = classify_document(self.spec, registry=self.registry)
            with self.assertRaises(MigrationError) as raised:
                _backup_document(
                    entry,
                    Path(backup_directory),
                    {"password": secret_value},
                )
            self.assertNotIn(secret_value, str(raised.exception))
            self.assertEqual(list(Path(backup_directory).iterdir()), [])

    def test_dangling_runtime_symlink_is_conflict(self):
        if os.name == "nt":
            self.skipTest("POSIX symlink classification test")
        target = self.root / "missing-target.json"
        self.runtime_file.unlink()
        self.runtime_file.symlink_to(target)

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, CONFLICT)
        self.assertNotIn("missing_runtime", entry.reason)

    def test_runtime_parent_symlink_is_conflict(self):
        if os.name == "nt":
            self.skipTest("POSIX symlink classification test")
        real_data = self.root / "real-data"
        real_runtime = real_data / "contracts"
        real_runtime.mkdir(parents=True)
        (real_runtime / "test.json").write_text(
            json.dumps(self.runtime_payload), encoding="utf-8"
        )
        self.runtime_file.unlink()
        self.runtime.rmdir()
        self.runtime.parent.rmdir()
        self.runtime.parent.symlink_to(real_data, target_is_directory=True)

        entry = classify_document(self.spec, registry=self.registry)

        self.assertEqual(entry.classification, CONFLICT)
        self.assertNotIn("missing_runtime", entry.reason)

    def test_windows_reparse_attribute_is_rejected_before_move(self):
        reparse_info = SimpleNamespace(
            st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        with (
            patch("apps.settings_center.document_migration.os.name", "nt"),
            patch(
                "apps.settings_center.document_migration.os.lstat",
                return_value=reparse_info,
            ),
        ):
            self.assertTrue(_windows_target_has_reparse_point(self.runtime_file))

    def test_windows_file_report_write_is_rejected_but_plan_output_contract_remains_explicit(self):
        with patch("apps.settings_center.document_migration.os.name", "nt"):
            with self.assertRaises(UnsupportedMigrationPlatform):
                _atomic_write(self.root / "report.json", "{}")

    def test_windows_plan_stdout_is_allowed_without_file_report(self):
        stream = StringIO()
        from . import document_migration as migration_module

        with patch.object(
            migration_module, "get_document_registry", return_value=self.registry
        ):
            call_command(
                "settings_documents_migrate",
                "--document-id",
                self.spec.document_id,
                stdout=stream,
            )
        self.assertIn('"mode": "plan"', stream.getvalue())

    def test_export_fails_closed_on_windows_before_creating_targets(self):
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        output = self.root / "export.json"
        manifest = self.root / "export.manifest.json"
        with patch("apps.settings_center.document_migration.os.name", "nt"):
            with self.assertRaises(UnsupportedMigrationPlatform):
                export_document(
                    self.spec.document_id,
                    output=output,
                    manifest_output=manifest,
                    registry=self.registry,
                )
        self.assertFalse(output.exists())
        self.assertFalse(manifest.exists())

    def test_plan_rejects_explicit_document_already_using_database_backend(self):
        database_spec = replace(self.spec, active_backend="database")
        database_registry = ConfigDocumentRegistry((database_spec,))
        with self.assertRaises(MigrationSliceError):
            plan_migration((database_spec.document_id,), registry=database_registry)

    def test_default_plan_skips_document_already_using_database_backend(self):
        database_spec = replace(self.spec, active_backend="database")
        database_registry = ConfigDocumentRegistry((database_spec,))

        self.assertEqual(plan_migration(registry=database_registry), ())

    def test_role_defaults_and_viewer_drift_requires_security_review(self):
        default = {"$defaults": {}, "viewer": {}, "roles": {}}
        runtime = {"roles": {}}
        self.default_file.write_text(json.dumps(default), encoding="utf-8")
        self.runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
        spec = ConfigDocumentSpec(
            "core.contract.role_rules",
            "accounts",
            "database_override",
            "contracts/test.json",
            1,
            lambda payload: None,
            "fail_closed",
            "editable",
            "manage_settings",
            "accounts",
        )

        entry = classify_document(spec, registry=ConfigDocumentRegistry((spec,)))

        self.assertEqual(entry.classification, SECURITY_REVIEW_REQUIRED)

    @skipUnless(connection.vendor == "postgresql", "security import проверяется на PostgreSQL")
    def test_exact_role_security_review_can_preserve_runtime_with_explicit_hashes(self):
        catalog = {"view_scope": {"type": "scope"}}
        administration = {"mode": "managed"}
        default = {
            "$capabilities": catalog,
            "$administration": administration,
            "$defaults": {"new_user_role": None},
            "viewer": {"view_scope": "department_branch"},
            "manager": {"view_scope": "all"},
        }
        runtime = {
            "$capabilities": catalog,
            "$administration": administration,
            "manager": {"view_scope": "department_branch"},
        }
        self.default_file.write_text(json.dumps(default), encoding="utf-8")
        self.runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
        spec = ConfigDocumentSpec(
            "core.contract.role_rules",
            "accounts",
            "database_override",
            "contracts/test.json",
            1,
            lambda payload: None,
            "fail_closed",
            "requires_domain_workflow",
            "manage_settings",
            "accounts",
        )
        registry = ConfigDocumentRegistry((spec,))
        actor = self._create_superuser()

        with TemporaryDirectory() as backup_directory:
            result = apply_migration(
                (spec.document_id,),
                actor=actor,
                backup_root=backup_directory,
                registry=registry,
                approved_role_runtime_document_hash=document_hash(runtime),
                approved_role_default_document_hash=document_hash(default),
                security_review_reason="Сохранить фактическую закрытую модель доступа.",
            )

        row = RuntimeSettingDocument.objects.get(document_id=spec.document_id)
        change = SettingsChange.objects.get(
            setting_id=spec.document_id,
            storage_kind="runtime_document",
        )
        self.assertEqual(row.payload, runtime)
        self.assertEqual(row.revision, 1)
        self.assertEqual(result[0].classification, ALREADY_IMPORTED)
        self.assertEqual(
            change.validation_result["security_review"]["decision"],
            "preserve_exact_runtime_payload",
        )

    @skipUnless(connection.vendor == "postgresql", "security import проверяется на PostgreSQL")
    def test_role_security_review_rejects_capability_catalog_drift(self):
        default = {
            "$capabilities": {"view_scope": {"type": "scope"}},
            "$administration": {},
            "$defaults": {},
            "viewer": {},
            "manager": {},
        }
        runtime = {
            "$capabilities": {"view_scope": {"type": "flag"}},
            "$administration": {},
            "manager": {},
        }
        self.default_file.write_text(json.dumps(default), encoding="utf-8")
        self.runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
        spec = ConfigDocumentSpec(
            "core.contract.role_rules",
            "accounts",
            "database_override",
            "contracts/test.json",
            1,
            lambda payload: None,
            "fail_closed",
            "requires_domain_workflow",
            "manage_settings",
            "accounts",
        )
        actor = self._create_superuser()
        with TemporaryDirectory() as backup_directory:
            with self.assertRaisesMessage(MigrationError, "$capabilities"):
                apply_migration(
                    (spec.document_id,),
                    actor=actor,
                    backup_root=backup_directory,
                    registry=ConfigDocumentRegistry((spec,)),
                    approved_role_runtime_document_hash=document_hash(runtime),
                    approved_role_default_document_hash=document_hash(default),
                    security_review_reason="Проверка отклонения каталога.",
                )
        self.assertFalse(RuntimeSettingDocument.objects.exists())

    def test_plan_is_stable_and_read_only(self):
        first = plan_migration((self.spec.document_id,), registry=self.registry)
        second = plan_migration((self.spec.document_id,), registry=self.registry)

        self.assertEqual(first[0].as_dict(), second[0].as_dict())
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)
        self.assertEqual(SettingsChange.objects.count(), 0)

    def test_backup_manifest_and_payload_hash_are_verified(self):
        self._audit_legacy_write()
        entry = classify_document(self.spec, registry=self.registry)
        with TemporaryDirectory() as backup_directory:
            record = _backup_document(entry, Path(backup_directory), self.runtime_payload)
            manifest = json.loads(Path(record.manifest_path).read_text(encoding="utf-8"))
            payload = json.loads(Path(record.payload_path).read_text(encoding="utf-8"))

        self.assertEqual(normalized_hash(payload), record.payload_hash)
        manifest_hash = manifest.pop("manifest_hash")
        self.assertEqual(document_hash(manifest), manifest_hash)
        self.assertEqual(manifest["document_id"], self.spec.document_id)
        self.assertEqual(manifest["runtime_hash"], normalized_hash(payload))
        self.assertEqual(manifest["document_hash"], document_hash(payload))
        self.assertEqual(manifest["default_hash"], entry.default_hash)

    def test_mixed_connected_slice_plans_audited_identical_and_missing(self):
        specs, files = self._make_mixed_specs()
        registry = ConfigDocumentRegistry(specs)
        self._audit_payload(
            specs[0],
            files["test.slice.a"][0],
            files["test.slice.a"][1],
        )
        entry_by_id = {
            entry.document_id: entry
            for entry in plan_migration(
                tuple(spec.document_id for spec in specs), registry=registry
            )
        }

        self.assertEqual(
            set(entry_by_id), {"test.slice.a", "test.slice.b", "test.slice.c"}
        )
        self.assertEqual(entry_by_id["test.slice.a"].classification, AUDITED_OVERRIDE)
        self.assertEqual(entry_by_id["test.slice.b"].classification, IDENTICAL_DEFAULT)
        self.assertEqual(entry_by_id["test.slice.c"].classification, MISSING_RUNTIME)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)

    @skipUnless(connection.vendor == "postgresql", "mixed apply проверяется на PostgreSQL")
    def test_mixed_connected_slice_applies_only_audited_member(self):
        specs, files = self._make_mixed_specs()
        registry = ConfigDocumentRegistry(specs)
        self._audit_payload(
            specs[0],
            files["test.slice.a"][0],
            files["test.slice.a"][1],
        )
        actor = self._create_superuser()
        with TemporaryDirectory() as backup_directory:
            result = apply_migration(
                tuple(spec.document_id for spec in specs),
                actor=actor,
                backup_root=backup_directory,
                registry=registry,
            )

        result_by_id = {entry.document_id: entry for entry in result}
        self.assertEqual(result_by_id["test.slice.a"].classification, "already_imported")
        self.assertEqual(result_by_id["test.slice.b"].classification, IDENTICAL_DEFAULT)
        self.assertEqual(result_by_id["test.slice.c"].classification, MISSING_RUNTIME)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 1)
        self.assertEqual(
            SettingsChange.objects.filter(action=SettingsChange.Action.APPLY).count(),
            2,
        )

    def test_sqlite_apply_rejected_before_backup_side_effect(self):
        if connection.vendor == "postgresql":
            self.skipTest("SQLite pre-backup rejection is backend-specific")
        actor = self._create_superuser()
        with TemporaryDirectory() as backup_directory, patch(
            "apps.settings_center.document_migration._backup_document",
            side_effect=AssertionError("backup must not be called"),
        ):
            with self.assertRaises(UnsupportedMigrationBackend):
                apply_migration(
                    (self.spec.document_id,),
                    actor=actor,
                    backup_root=backup_directory,
                    registry=self.registry,
                )
            self.assertEqual(list(Path(backup_directory).iterdir()), [])

    def test_apply_requires_explicit_nonempty_slice(self):
        with self.assertRaises(MigrationSliceError):
            apply_migration(
                (),
                actor=self._create_superuser(),
                backup_root=self.root,
                registry=self.registry,
            )

    @skipUnless(connection.vendor == "postgresql", "late transaction failure проверяется на PostgreSQL")
    def test_late_settings_change_failure_rolls_back_document_and_audit(self):
        self._audit_legacy_write()
        actor = self._create_superuser()
        with TemporaryDirectory() as backup_directory, patch.object(
            SettingsChange.objects,
            "create",
            side_effect=RuntimeError("late audit failure"),
        ):
            with self.assertRaises(RuntimeError):
                apply_migration(
                    (self.spec.document_id,),
                    actor=actor,
                    backup_root=backup_directory,
                    registry=self.registry,
                )

        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)
        self.assertEqual(SettingsChange.objects.count(), 1)

    @skipUnless(connection.vendor == "postgresql", "multi-document rollback проверяется на PostgreSQL")
    def test_second_audited_document_failure_rolls_back_complete_slice(self):
        specs, files = self._make_mixed_specs()
        registry = ConfigDocumentRegistry(specs)
        second_runtime = {"name": "b-operator"}
        (self.runtime / "slice-b.json").write_text(
            json.dumps(second_runtime), encoding="utf-8"
        )
        self._audit_payload(specs[0], files["test.slice.a"][0], files["test.slice.a"][1])
        self._audit_payload(specs[1], files["test.slice.b"][0], second_runtime)
        actor = self._create_superuser()
        real_create = SettingsChange.objects.create
        runtime_document_writes = 0

        def fail_second_runtime_document(*args, **kwargs):
            nonlocal runtime_document_writes
            if kwargs.get("storage_kind") == "runtime_document":
                runtime_document_writes += 1
                if runtime_document_writes == 2:
                    raise RuntimeError("second document audit failure")
            return real_create(*args, **kwargs)

        with TemporaryDirectory() as backup_directory, patch.object(
            SettingsChange.objects,
            "create",
            side_effect=fail_second_runtime_document,
        ):
            with self.assertRaises(RuntimeError):
                apply_migration(
                    tuple(spec.document_id for spec in specs),
                    actor=actor,
                    backup_root=backup_directory,
                    registry=registry,
                )

        self.assertEqual(runtime_document_writes, 2)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)
        self.assertEqual(SettingsChange.objects.count(), 2)

    @skipUnless(connection.vendor == "postgresql", "mutation recheck проверяется на PostgreSQL")
    def test_runtime_mutation_after_initial_plan_is_rejected_without_rows(self):
        self._audit_legacy_write()
        actor = self._create_superuser()
        from . import document_migration as migration_module

        real_backup = migration_module._backup_document

        def mutate_after_backup(entry, root, payload):
            record = real_backup(entry, root, payload)
            self.runtime_file.write_text(
                json.dumps({"enabled": True, "label": "mutated-after-plan"}),
                encoding="utf-8",
            )
            return record

        with TemporaryDirectory() as backup_directory, patch.object(
            migration_module,
            "_backup_document",
            side_effect=mutate_after_backup,
        ):
            with self.assertRaises(MigrationError):
                apply_migration(
                    (self.spec.document_id,),
                    actor=actor,
                    backup_root=backup_directory,
                    registry=self.registry,
                )

        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)
        self.assertEqual(SettingsChange.objects.count(), 1)

    @skipUnless(connection.vendor == "postgresql", "mutation after current_plans проверяется на PostgreSQL")
    def test_runtime_mutation_after_current_plans_recheck_is_rejected_before_insert(self):
        self._audit_legacy_write()
        actor = self._create_superuser()
        from . import document_migration as migration_module

        real_classify = migration_module.classify_document
        classify_calls = 0

        def classify_and_mutate_after_recheck(spec, **kwargs):
            nonlocal classify_calls
            classify_calls += 1
            result = real_classify(spec, **kwargs)
            if classify_calls == 2:
                self.runtime_file.write_text(
                    json.dumps({"enabled": True, "label": "mutated-after-current-plans"}),
                    encoding="utf-8",
                )
            return result

        with TemporaryDirectory() as backup_directory, patch.object(
            migration_module,
            "classify_document",
            side_effect=classify_and_mutate_after_recheck,
        ):
            with self.assertRaises(MigrationError):
                apply_migration(
                    (self.spec.document_id,),
                    actor=actor,
                    backup_root=backup_directory,
                    registry=self.registry,
                )

        self.assertEqual(classify_calls, 2)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)
        self.assertEqual(SettingsChange.objects.count(), 1)

    def test_migrate_command_defaults_to_read_only_plan_and_local_output(self):
        output = self.root / ".local" / "migration-plan.json"
        from . import document_migration as migration_module

        with patch.object(
            migration_module, "get_document_registry", return_value=self.registry
        ):
            call_command(
                "settings_documents_migrate",
                "--document-id",
                self.spec.document_id,
                "--output",
                str(output),
            )

        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(RuntimeSettingDocument.objects.count(), 0)
        self.assertEqual(SettingsChange.objects.count(), 0)

    def test_migrate_command_rejects_output_before_apply(self):
        actor = self._create_superuser()
        with TemporaryDirectory() as backup_directory, patch(
            "apps.settings_center.management.commands.settings_documents_migrate.apply_migration",
            side_effect=AssertionError("apply must not run"),
        ):
            with self.assertRaises(CommandError) as raised:
                call_command(
                    "settings_documents_migrate",
                    "--apply",
                    "--document-id",
                    self.spec.document_id,
                    "--actor-id",
                    str(actor.pk),
                    "--backup-root",
                    backup_directory,
                    "--output",
                    str(self.root / "operator-output.json"),
                )
        self.assertIn(".local", str(raised.exception))

    @skipUnless(connection.vendor == "postgresql", "command apply проверяется на PostgreSQL")
    def test_migrate_command_apply_end_to_end(self):
        self._audit_legacy_write()
        actor = self._create_superuser()
        output = self.root / ".local" / "apply-result.json"
        from . import document_migration as migration_module

        with TemporaryDirectory() as backup_directory, patch.object(
            migration_module, "get_document_registry", return_value=self.registry
        ):
            call_command(
                "settings_documents_migrate",
                "--apply",
                "--document-id",
                self.spec.document_id,
                "--actor-id",
                str(actor.pk),
                "--backup-root",
                backup_directory,
                "--output",
                str(output),
            )

        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["documents"][0]["classification"], "already_imported")
        self.assertTrue(
            RuntimeSettingDocument.objects.filter(document_id=self.spec.document_id).exists()
        )

    def test_export_command_end_to_end(self):
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        output = self.root / ".local" / "command-export.json"
        manifest = self.root / ".local" / "command-export.manifest.json"
        from . import document_migration as migration_module

        with patch.object(
            migration_module, "get_document_registry", return_value=self.registry
        ):
            call_command(
                "settings_documents_export",
                "--document-id",
                self.spec.document_id,
                "--output",
                str(output),
                "--manifest",
                str(manifest),
            )

        payload = json.loads(output.read_text(encoding="utf-8"))
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload, self.default_payload)
        self.assertEqual(manifest_payload["content_hash"], document_hash(payload))

    def test_export_rejects_same_payload_and_manifest_path(self):
        output = self.root / ".local" / "same.json"
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        with self.assertRaises(UnsafeMigrationPath):
            export_document(
                self.spec.document_id,
                output=output,
                manifest_output=output,
                registry=self.registry,
            )

    def test_export_does_not_overwrite_existing_evidence(self):
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        output = self.root / ".local" / "existing.json"
        manifest = self.root / ".local" / "existing.manifest.json"
        output.parent.mkdir(parents=True)
        output.write_text("operator evidence", encoding="utf-8")

        with self.assertRaises(UnsafeMigrationPath):
            export_document(
                self.spec.document_id,
                output=output,
                manifest_output=manifest,
                registry=self.registry,
            )

        self.assertEqual(output.read_text(encoding="utf-8"), "operator evidence")
        self.assertFalse(manifest.exists())

    def test_export_verifies_post_write_payload_and_manifest_hashes(self):
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        output = self.root / ".local" / "effective.json"
        manifest = self.root / ".local" / "effective.manifest.json"
        result = export_document(
            self.spec.document_id,
            output=output,
            manifest_output=manifest,
            registry=self.registry,
        )

        payload = json.loads(output.read_text(encoding="utf-8"))
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_hash = manifest_payload.pop("manifest_hash")
        self.assertEqual(result["content_hash"], document_hash(payload))
        self.assertEqual(manifest_payload["content_hash"], document_hash(payload))
        self.assertEqual(document_hash(manifest_payload), manifest_hash)

    def test_export_removes_own_partial_files_after_post_write_mismatch(self):
        self.runtime_file.write_text(json.dumps(self.default_payload), encoding="utf-8")
        output = self.root / ".local" / "tampered.json"
        manifest = self.root / ".local" / "tampered.manifest.json"
        from . import document_migration as migration_module

        real_atomic_write = migration_module._atomic_write

        def write_and_tamper(path, content, *, overwrite=True):
            real_atomic_write(path, content, overwrite=overwrite)
            if Path(path) == output:
                Path(path).write_text(json.dumps({"tampered": True}), encoding="utf-8")

        with patch.object(
            migration_module,
            "_atomic_write",
            side_effect=write_and_tamper,
        ):
            with self.assertRaises(MigrationError):
                export_document(
                    self.spec.document_id,
                    output=output,
                    manifest_output=manifest,
                    registry=self.registry,
                )
        self.assertFalse(output.exists())
        self.assertFalse(manifest.exists())

    @skipUnless(connection.vendor == "postgresql", "advisory-lock apply проверяется на PostgreSQL")
    def test_apply_imports_audited_override_once(self):
        self._audit_legacy_write()
        with TemporaryDirectory() as backup_directory:
            actor = self._create_superuser()
            first = apply_migration(
                (self.spec.document_id,),
                actor=actor,
                backup_root=backup_directory,
                registry=self.registry,
            )
            changes_after_first = SettingsChange.objects.count()
            second = apply_migration(
                (self.spec.document_id,),
                actor=actor,
                backup_root=backup_directory,
                registry=self.registry,
            )
            changes_after_second = SettingsChange.objects.count()

        self.assertEqual(first[0].db_revision, 1)
        self.assertEqual(second[0].classification, "already_imported")
        self.assertEqual(changes_after_second, changes_after_first)
        self.assertEqual(RuntimeSettingDocument.objects.count(), 1)
        self.assertEqual(SettingsChange.objects.filter(action=SettingsChange.Action.APPLY).count(), 2)

    def test_apply_fails_closed_on_windows_before_backup(self):
        actor = self._create_superuser()
        with patch("apps.settings_center.document_migration.os.name", "nt"), patch(
            "apps.settings_center.document_migration._backup_document",
            side_effect=AssertionError("backup must not run"),
        ):
            with self.assertRaises(UnsupportedMigrationPlatform):
                apply_migration(
                    (self.spec.document_id,),
                    actor=actor,
                    backup_root=self.root,
                    registry=self.registry,
                )

    def _create_superuser(self):
        return get_user_model().objects.create_superuser(
            username="migration-admin",
            password="safe-test-password",
        )

    def _audit_payload(self, spec, default_payload, runtime_payload):
        SettingsChange.objects.create(
            setting_id=spec.document_id,
            domain=spec.domain,
            storage_kind="runtime_contract",
            action=SettingsChange.Action.APPLY,
            status=SettingsChange.Status.APPLIED,
            before_hash=normalized_hash(default_payload),
            after_hash=normalized_hash(runtime_payload),
            before_snapshot=default_payload,
            after_snapshot=runtime_payload,
        )

    def _make_mixed_specs(self):
        defaults = {
            "test.slice.a": {"name": "a-default"},
            "test.slice.b": {"name": "b-default"},
            "test.slice.c": {"name": "c-default"},
        }
        runtimes = {
            "test.slice.a": {"name": "a-operator"},
            "test.slice.b": defaults["test.slice.b"],
        }
        specs = (
            ConfigDocumentSpec(
                "test.slice.a",
                "test",
                "database_override",
                "contracts/slice-a.json",
                1,
                lambda payload: None,
                "fail_closed",
                "editable",
                "manage_settings",
                "test",
                cross_document_ids=("test.slice.b", "test.slice.c"),
                cross_validator=lambda payload, related: None,
            ),
            ConfigDocumentSpec(
                "test.slice.b",
                "test",
                "database_override",
                "contracts/slice-b.json",
                1,
                lambda payload: None,
                "fail_closed",
                "editable",
                "manage_settings",
                "test",
            ),
            ConfigDocumentSpec(
                "test.slice.c",
                "test",
                "database_override",
                "contracts/slice-c.json",
                1,
                lambda payload: None,
                "fail_closed",
                "editable",
                "manage_settings",
                "test",
            ),
        )
        files = {}
        for document_id, payload in defaults.items():
            suffix = document_id.rsplit(".", 1)[-1]
            default_file = self.contracts / f"slice-{suffix}.json"
            default_file.write_text(json.dumps(payload), encoding="utf-8")
            runtime_file = self.runtime / f"slice-{suffix}.json"
            if document_id in runtimes:
                runtime_file.write_text(
                    json.dumps(runtimes[document_id]), encoding="utf-8"
                )
            files[document_id] = (payload, runtimes.get(document_id))
        return specs, files
