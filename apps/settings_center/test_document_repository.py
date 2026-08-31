from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import math
from dataclasses import replace
from types import SimpleNamespace
from threading import Barrier, Thread
from unittest import skipUnless
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, connections
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase

from .document_hashes import InvalidDocumentPayload, canonical_json, document_hash
from .document_registry import ConfigDocumentRegistry, get_document_registry
from .document_repository import (
    ConfigDocumentRepository,
    ConfigurationUnavailable,
    get_document_degradation_state,
    probe_settings_document_health,
    reset_document_degradation_state_for_tests,
)
from .document_services import (
    ConfigDocumentWriter,
    DocumentMigrationRequired,
    DocumentWriteError,
    DocumentWriteConflict,
    ExpectedDocumentVersion,
    SecretBearingDocument,
    UnsupportedDocumentWriteBackend,
    advisory_lock_key,
)
from .models import RuntimeSettingDocument, SettingsChange


User = get_user_model()


@pytest.mark.unit
class DocumentHashTests(SimpleTestCase):
    def test_hash_is_stable_for_object_key_order(self):
        left = {"b": [2, 1], "a": {"x": "значение"}}
        right = {"a": {"x": "значение"}, "b": [2, 1]}

        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(document_hash(left), document_hash(right))
        self.assertEqual(len(document_hash(left)), 64)

    def test_non_json_values_and_non_finite_numbers_are_rejected(self):
        for invalid in (
            {"items": {1, 2}},
            {"value": math.nan},
            {"value": math.inf},
            {"items": (1, 2)},
            {1: "non-string-key"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InvalidDocumentPayload):
                canonical_json(invalid)


def _database_spec(document_id="waiting_list.contract.status_colors"):
    return replace(get_document_registry().get(document_id), active_backend="database")


def _registry(*specs):
    return ConfigDocumentRegistry(specs)


@pytest.mark.integration
class DocumentRepositoryTests(TestCase):
    def setUp(self):
        reset_document_degradation_state_for_tests()
        self.spec = _database_spec()
        self.repository = ConfigDocumentRepository(_registry(self.spec))

    def test_git_default_is_returned_when_override_is_absent(self):
        snapshot = self.repository.get_document(self.spec.document_id)

        self.assertEqual(snapshot.source, "git_default")
        self.assertEqual(snapshot.revision, 0)
        self.assertEqual(snapshot.content_hash, snapshot.default_hash)

    def test_valid_database_override_has_precedence_and_is_copied(self):
        default = self.repository.get_document(self.spec.document_id)
        payload = deepcopy(default.payload)
        payload["statuses"]["waiting"]["color"] = "#123456"
        content_hash = document_hash(payload)
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=payload,
            revision=3,
            content_hash=content_hash,
            default_hash=default.default_hash,
        )

        snapshot = self.repository.get_document(self.spec.document_id)
        snapshot.payload["statuses"]["waiting"]["color"] = "#ffffff"
        second = self.repository.get_document(self.spec.document_id)

        self.assertEqual(snapshot.source, "database_override")
        self.assertEqual(snapshot.revision, 3)
        self.assertEqual(second.payload["statuses"]["waiting"]["color"], "#123456")

    def test_visible_fallback_is_marked_when_override_hash_is_corrupt(self):
        default = self.repository.get_document(self.spec.document_id)
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=default.payload,
            revision=1,
            content_hash="0" * 64,
            default_hash=default.default_hash,
        )

        snapshot = self.repository.get_document(self.spec.document_id)

        self.assertTrue(snapshot.degraded)
        self.assertEqual(snapshot.source, "git_default_fallback")

    def test_fail_closed_document_does_not_fallback(self):
        critical = replace(self.spec, document_id="test.critical", failure_policy="fail_closed")
        repository = ConfigDocumentRepository(_registry(critical))
        default = repository.get_document(critical.document_id)
        RuntimeSettingDocument.objects.create(
            document_id=critical.document_id,
            schema_version=critical.schema_version,
            payload=default.payload,
            revision=1,
            content_hash="0" * 64,
            default_hash=default.default_hash,
        )

        with self.assertRaises(ConfigurationUnavailable):
            repository.get_document(critical.document_id)

    def test_request_keeps_one_revision(self):
        default = self.repository.get_document(self.spec.document_id)
        payload = deepcopy(default.payload)
        payload["statuses"]["waiting"]["color"] = "#111111"
        row = RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=payload,
            revision=1,
            content_hash=document_hash(payload),
            default_hash=default.default_hash,
        )
        request = RequestFactory().get("/")
        first = self.repository.get_document(self.spec.document_id, request=request)
        changed = deepcopy(payload)
        changed["statuses"]["waiting"]["color"] = "#222222"
        row.payload = changed
        row.content_hash = document_hash(changed)
        row.revision = 2
        row.save()

        second = self.repository.get_document(self.spec.document_id, request=request)

        self.assertEqual(first.revision, 1)
        self.assertEqual(second.revision, 1)
        self.assertEqual(second.payload["statuses"]["waiting"]["color"], "#111111")

    def test_related_database_rows_are_loaded_with_one_query(self):
        workflow_spec = _database_spec("core.contract.workflow_rules")
        colors_spec = _database_spec("workorders.contract.status_colors")
        repository = ConfigDocumentRepository(_registry(workflow_spec, colors_spec))

        with self.assertNumQueries(1):
            snapshots = repository.get_snapshot(
                (workflow_spec.document_id, colors_spec.document_id)
            )

        self.assertEqual(
            set(snapshots),
            {workflow_spec.document_id, colors_spec.document_id},
        )

    def test_default_hash_drift_is_visible_without_rewriting_payload(self):
        default = self.repository.get_document(self.spec.document_id)
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=default.payload,
            revision=1,
            content_hash=default.content_hash,
            default_hash="0" * 64,
        )

        snapshot = self.repository.get_document(self.spec.document_id)

        self.assertTrue(snapshot.migration_required)
        state = get_document_degradation_state()
        self.assertTrue(state["migration_required"])
        self.assertEqual(
            state["documents"][self.spec.document_id]["code"],
            "default_drift",
        )

    def test_cross_fallback_must_leave_final_connected_slice_valid(self):
        dependency = self.spec

        def always_invalid(candidate, related):
            raise ValueError("invalid connected slice")

        dependent = replace(
            _database_spec("ai.contract.chat_settings"),
            validator=lambda payload: None,
            cross_document_ids=(dependency.document_id,),
            cross_validator=always_invalid,
        )
        repository = ConfigDocumentRepository(_registry(dependency, dependent))

        with self.assertRaises(ConfigurationUnavailable):
            repository.get_document(dependent.document_id)

    def test_health_reports_degradation_and_clears_it_after_recovery(self):
        default = self.repository.get_document(self.spec.document_id)
        row = RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=default.payload,
            revision=1,
            content_hash="0" * 64,
            default_hash=default.default_hash,
        )
        with patch(
            "apps.settings_center.document_repository.get_document_registry",
            return_value=self.repository.registry,
        ):
            degraded = probe_settings_document_health()
            row.content_hash = default.content_hash
            row.save(update_fields=["content_hash"])
            recovered = probe_settings_document_health()

        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(
            degraded["documents"][self.spec.document_id]["code"],
            "content_hash_mismatch",
        )
        self.assertEqual(recovered["status"], "ok")
        self.assertFalse(get_document_degradation_state()["degraded"])

    def test_health_reports_schema_mismatch_without_exception_text(self):
        default = self.repository.get_document(self.spec.document_id)
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version + 1,
            payload=default.payload,
            revision=1,
            content_hash=default.content_hash,
            default_hash=default.default_hash,
        )
        with patch(
            "apps.settings_center.document_repository.get_document_registry",
            return_value=self.repository.registry,
        ):
            health = probe_settings_document_health()

        item = health["documents"][self.spec.document_id]
        self.assertEqual(item["status"], "migration_required")
        self.assertEqual(item["code"], "schema_mismatch")
        self.assertNotIn("message", item)

    def test_validly_hashed_database_secret_is_never_returned(self):
        default = self.repository.get_document(self.spec.document_id)
        secret_payload = {"password": "must-not-be-returned"}
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=secret_payload,
            revision=1,
            content_hash=document_hash(secret_payload),
            default_hash=default.default_hash,
        )

        snapshot = self.repository.get_document(self.spec.document_id)

        self.assertEqual(snapshot.source, "git_default_fallback")
        self.assertNotIn("password", snapshot.payload)
        self.assertEqual(
            get_document_degradation_state()["documents"][self.spec.document_id]["code"],
            "raw_secret_forbidden",
        )


@pytest.mark.integration
class RuntimeDocumentMigrationGuardTests(TestCase):
    def test_reverse_migration_refuses_to_drop_nonempty_store(self):
        RuntimeSettingDocument.objects.create(
            document_id="test.reverse-guard",
            schema_version=1,
            payload={},
            revision=1,
            content_hash=document_hash({}),
            default_hash=document_hash({}),
        )
        migration = import_module(
            "apps.settings_center.migrations.0004_settingschange_document_revision_after_and_more"
        )
        fake_apps = SimpleNamespace(
            get_model=lambda app_label, model_name: RuntimeSettingDocument
        )

        with self.assertRaisesRegex(RuntimeError, "Обратная миграция запрещена"):
            migration.refuse_reverse_with_runtime_documents(fake_apps, None)


@pytest.mark.integration
class DocumentWriterBackendTests(TestCase):
    def test_sqlite_writer_is_rejected_without_side_effects(self):
        if connection.vendor == "postgresql":
            self.skipTest("Проверка относится к SQLite development backend.")
        actor = User.objects.create_superuser(username="document-writer", password="x")
        spec = _database_spec()
        repository = ConfigDocumentRepository(_registry(spec))
        current = repository.get_document(spec.document_id)
        candidate = deepcopy(current.payload)
        candidate["statuses"]["waiting"]["color"] = "#123456"

        with self.assertRaises(UnsupportedDocumentWriteBackend):
            ConfigDocumentWriter(_registry(spec)).save_document(
                actor=actor,
                document_id=spec.document_id,
                payload=candidate,
                expected_revision=current.revision,
                expected_content_hash=current.content_hash,
            )

        self.assertFalse(RuntimeSettingDocument.objects.exists())
        self.assertFalse(SettingsChange.objects.exists())

    def test_advisory_lock_key_is_stable_signed_bigint(self):
        first = advisory_lock_key("waiting_list.contract.status_colors")
        self.assertEqual(first, advisory_lock_key("waiting_list.contract.status_colors"))
        self.assertNotEqual(first, advisory_lock_key("ai.contract.chat_settings"))
        self.assertGreaterEqual(first, -(1 << 63))
        self.assertLess(first, 1 << 63)

    def test_domain_workflow_rejects_unrelated_document_in_privileged_slice(self):
        role = _database_spec("core.contract.role_rules")
        workflow = _database_spec("core.contract.workflow_rules")
        colors = _database_spec("workorders.contract.status_colors")
        waiting = _database_spec()
        registry = _registry(role, workflow, colors, waiting)

        with self.assertRaisesRegex(DocumentWriteError, "одной связанной компоненты"):
            ConfigDocumentWriter(registry).save_documents_via_domain_workflow(
                actor=None,
                candidates={role.document_id: {}, waiting.document_id: {}},
                expected={
                    role.document_id: ExpectedDocumentVersion(0, "0" * 64),
                    waiting.document_id: ExpectedDocumentVersion(0, "0" * 64),
                },
                authorize=lambda actor: None,
            )


@skipUnless(connection.vendor == "postgresql", "Требуется PostgreSQL")
@pytest.mark.integration
@pytest.mark.serial
class PostgreSQLDocumentWriterTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.actor = User.objects.create_superuser(username="pg-document-writer", password="x")
        self.spec = _database_spec()
        self.registry = _registry(self.spec)
        self.repository = ConfigDocumentRepository(self.registry)
        self.writer = ConfigDocumentWriter(self.registry)

    def _candidate(self, color):
        current = self.repository.get_document(self.spec.document_id)
        payload = deepcopy(current.payload)
        payload["statuses"]["waiting"]["color"] = color
        return current, payload

    @staticmethod
    def _security_slice():
        role = _database_spec("core.contract.role_rules")
        workflow = _database_spec("core.contract.workflow_rules")
        colors = _database_spec("workorders.contract.status_colors")
        registry = _registry(role, workflow, colors)
        return role, workflow, colors, registry

    @staticmethod
    def _changed_role(payload, suffix):
        candidate = deepcopy(payload)
        role_code = next(key for key in candidate if not key.startswith("$"))
        candidate[role_code]["display_name"] += suffix
        return candidate

    @staticmethod
    def _changed_workflow(payload, remove_index=0):
        candidate = deepcopy(payload)
        source = next(
            key for key, targets in candidate["transitions"].items() if targets
        )
        targets = candidate["transitions"][source]
        candidate["transitions"][source] = (
            targets[:remove_index] + targets[remove_index + 1 :]
        )
        return candidate

    def test_insert_update_and_audit_are_one_monotonic_history(self):
        current, first_payload = self._candidate("#111111")
        first = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=first_payload,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        second_payload = deepcopy(first.payload)
        second_payload["statuses"]["waiting"]["color"] = "#222222"
        second = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=second_payload,
            expected_revision=first.revision,
            expected_content_hash=first.content_hash,
        )

        self.assertEqual((first.revision, second.revision), (1, 2))
        self.assertEqual(
            list(
                SettingsChange.objects.order_by("document_revision_after").values_list(
                    "document_revision_before", "document_revision_after", "status"
                )
            ),
            [
                (None, 1, SettingsChange.Status.APPLIED),
                (1, 2, SettingsChange.Status.APPLIED),
            ],
        )

    def test_concurrent_first_insert_has_one_success_and_one_stale_conflict(self):
        current, first_payload = self._candidate("#111111")
        second_payload = deepcopy(first_payload)
        second_payload["statuses"]["waiting"]["color"] = "#222222"
        barrier = Barrier(2)
        outcomes = []

        def write(payload):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                actor = User.objects.get(pk=self.actor.pk)
                result = ConfigDocumentWriter(self.registry).save_document(
                    actor=actor,
                    document_id=self.spec.document_id,
                    payload=payload,
                    expected_revision=current.revision,
                    expected_content_hash=current.content_hash,
                )
                outcomes.append(("success", result.revision))
            except DocumentWriteConflict:
                outcomes.append(("conflict", None))
            finally:
                connections.close_all()

        threads = [Thread(target=write, args=(payload,)) for payload in (first_payload, second_payload)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, [("success", 1), ("conflict", None)])
        self.assertEqual(RuntimeSettingDocument.objects.get().revision, 1)
        self.assertEqual(SettingsChange.objects.count(), 1)

    def test_concurrent_update_has_one_success_and_one_stale_conflict(self):
        current, first_payload = self._candidate("#111111")
        applied = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=first_payload,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        payloads = []
        for color in ("#222222", "#333333"):
            payload = deepcopy(applied.payload)
            payload["statuses"]["waiting"]["color"] = color
            payloads.append(payload)
        barrier = Barrier(2)
        outcomes = []

        def write(payload):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                actor = User.objects.get(pk=self.actor.pk)
                result = ConfigDocumentWriter(self.registry).save_document(
                    actor=actor,
                    document_id=self.spec.document_id,
                    payload=payload,
                    expected_revision=applied.revision,
                    expected_content_hash=applied.content_hash,
                )
                outcomes.append(("success", result.revision))
            except DocumentWriteConflict:
                outcomes.append(("conflict", None))
            finally:
                connections.close_all()

        threads = [Thread(target=write, args=(payload,)) for payload in payloads]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, [("success", 2), ("conflict", None)])
        self.assertEqual(RuntimeSettingDocument.objects.get().revision, 2)
        self.assertEqual(SettingsChange.objects.count(), 2)

    def test_noncooperating_unique_insert_is_classified_as_conflict(self):
        current, payload = self._candidate("#111111")
        cause = Exception("duplicate")
        cause.sqlstate = "23505"
        integrity_error = IntegrityError("duplicate")
        integrity_error.__cause__ = cause

        with patch.object(RuntimeSettingDocument, "save", side_effect=integrity_error):
            with self.assertRaises(DocumentWriteConflict):
                self.writer.save_document(
                    actor=self.actor,
                    document_id=self.spec.document_id,
                    payload=payload,
                    expected_revision=current.revision,
                    expected_content_hash=current.content_hash,
                )

        self.assertFalse(RuntimeSettingDocument.objects.exists())
        self.assertFalse(SettingsChange.objects.exists())

    def test_audit_failure_rolls_back_document(self):
        current, payload = self._candidate("#111111")
        with patch.object(SettingsChange.objects, "create", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                self.writer.save_document(
                    actor=self.actor,
                    document_id=self.spec.document_id,
                    payload=payload,
                    expected_revision=current.revision,
                    expected_content_hash=current.content_hash,
                )

        self.assertFalse(RuntimeSettingDocument.objects.exists())

    def test_stale_update_does_not_create_audit(self):
        current, payload = self._candidate("#111111")
        applied = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=payload,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        changed = deepcopy(applied.payload)
        changed["statuses"]["waiting"]["color"] = "#222222"

        with self.assertRaises(DocumentWriteConflict):
            self.writer.save_document(
                actor=self.actor,
                document_id=self.spec.document_id,
                payload=changed,
                expected_revision=0,
                expected_content_hash=current.content_hash,
            )

        self.assertEqual(RuntimeSettingDocument.objects.get().revision, 1)
        self.assertEqual(SettingsChange.objects.count(), 1)

    def test_raw_secret_field_is_rejected_before_persistence_and_audit(self):
        current, payload = self._candidate("#111111")
        payload["password"] = "must-not-be-stored"

        with self.assertRaises(SecretBearingDocument):
            self.writer.save_document(
                actor=self.actor,
                document_id=self.spec.document_id,
                payload=payload,
                expected_revision=current.revision,
                expected_content_hash=current.content_hash,
            )

        self.assertFalse(RuntimeSettingDocument.objects.exists())
        self.assertFalse(SettingsChange.objects.exists())

    def test_raw_secret_in_audit_context_is_rejected_before_persistence(self):
        current, payload = self._candidate("#111111")

        with self.assertRaises(SecretBearingDocument):
            self.writer.save_document(
                actor=self.actor,
                document_id=self.spec.document_id,
                payload=payload,
                expected_revision=current.revision,
                expected_content_hash=current.content_hash,
                audit_context={"client_secret": "must-not-be-stored"},
            )

        self.assertFalse(RuntimeSettingDocument.objects.exists())
        self.assertFalse(SettingsChange.objects.exists())

    def test_default_drift_blocks_ordinary_write_until_migration(self):
        current, payload = self._candidate("#111111")
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version,
            payload=current.payload,
            revision=1,
            content_hash=current.content_hash,
            default_hash="0" * 64,
        )

        with self.assertRaises(DocumentMigrationRequired):
            self.writer.save_document(
                actor=self.actor,
                document_id=self.spec.document_id,
                payload=payload,
                expected_revision=1,
                expected_content_hash=current.content_hash,
            )

        self.assertFalse(SettingsChange.objects.exists())

    def test_schema_mismatch_blocks_ordinary_write_until_migration(self):
        current, payload = self._candidate("#111111")
        RuntimeSettingDocument.objects.create(
            document_id=self.spec.document_id,
            schema_version=self.spec.schema_version + 1,
            payload=current.payload,
            revision=1,
            content_hash=current.content_hash,
            default_hash=current.default_hash,
        )

        with self.assertRaises(DocumentMigrationRequired):
            self.writer.save_document(
                actor=self.actor,
                document_id=self.spec.document_id,
                payload=payload,
                expected_revision=1,
                expected_content_hash=current.content_hash,
            )

        self.assertFalse(SettingsChange.objects.exists())

    def test_drift_in_dependency_blocks_write_of_related_document(self):
        _role, workflow, colors, registry = self._security_slice()
        repository = ConfigDocumentRepository(registry)
        current = repository.get_snapshot((workflow.document_id, colors.document_id))
        workflow_snapshot = current[workflow.document_id]
        RuntimeSettingDocument.objects.create(
            document_id=workflow.document_id,
            schema_version=workflow.schema_version,
            payload=workflow_snapshot.payload,
            revision=1,
            content_hash=workflow_snapshot.content_hash,
            default_hash="0" * 64,
        )
        color_snapshot = current[colors.document_id]
        color_payload = deepcopy(color_snapshot.payload)
        first_status = next(iter(color_payload["statuses"]))
        color_payload["statuses"][first_status]["color"] = "#123456"

        with self.assertRaises(DocumentMigrationRequired):
            ConfigDocumentWriter(registry).save_document(
                actor=self.actor,
                document_id=colors.document_id,
                payload=color_payload,
                expected_revision=color_snapshot.revision,
                expected_content_hash=color_snapshot.content_hash,
            )

        self.assertEqual(RuntimeSettingDocument.objects.count(), 1)
        self.assertFalse(SettingsChange.objects.exists())

    def test_postgresql_jsonb_preserves_supported_numeric_values(self):
        payload = {"integer": 7, "fraction": 1.25, "items": [0, -2, 3.5]}
        RuntimeSettingDocument.objects.create(
            document_id="test.numeric-jsonb",
            schema_version=1,
            payload=payload,
            revision=1,
            content_hash=document_hash(payload),
            default_hash=document_hash(payload),
        )

        self.assertEqual(
            RuntimeSettingDocument.objects.get(document_id="test.numeric-jsonb").payload,
            payload,
        )

    def test_rollback_creates_new_revision(self):
        current, payload = self._candidate("#111111")
        applied = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=payload,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        source = SettingsChange.objects.get(document_revision_after=1)

        restored = self.writer.rollback_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            source_change_id=source.pk,
            expected_revision=applied.revision,
            expected_content_hash=applied.content_hash,
        )

        self.assertEqual(restored.revision, 2)
        self.assertEqual(restored.payload, current.payload)
        rollback = SettingsChange.objects.get(action=SettingsChange.Action.ROLLBACK)
        self.assertEqual(rollback.rollback_of_id, source.pk)
        self.assertEqual(rollback.document_revision_after, 2)

    def test_multi_document_domain_write_locks_sorted_slice(self):
        workflow_spec = replace(
            get_document_registry().get("core.contract.workflow_rules"),
            active_backend="database",
            write_policy="requires_domain_workflow",
        )
        colors_spec = replace(
            get_document_registry().get("workorders.contract.status_colors"),
            active_backend="database",
        )
        registry = _registry(workflow_spec, colors_spec)
        repository = ConfigDocumentRepository(registry)
        writer = ConfigDocumentWriter(registry)
        current = repository.get_snapshot(
            (colors_spec.document_id, workflow_spec.document_id)
        )
        workflow = deepcopy(current[workflow_spec.document_id].payload)
        source = next(key for key, targets in workflow["transitions"].items() if targets)
        workflow["transitions"][source] = workflow["transitions"][source][1:]
        colors = deepcopy(current[colors_spec.document_id].payload)
        first_status = next(iter(colors["statuses"]))
        colors["statuses"][first_status]["color"] = "#123456"
        candidates = {
            colors_spec.document_id: colors,
            workflow_spec.document_id: workflow,
        }
        expected = {
            document_id: ExpectedDocumentVersion(snapshot.revision, snapshot.content_hash)
            for document_id, snapshot in current.items()
        }

        with patch.object(writer, "_acquire_locks", wraps=writer._acquire_locks) as acquire:
            result = writer.save_documents_via_domain_workflow(
                actor=self.actor,
                candidates=candidates,
                expected=expected,
                authorize=lambda actor: None,
            )

        locked_ids = acquire.call_args.args[0]
        self.assertEqual(tuple(locked_ids), tuple(sorted(locked_ids)))
        self.assertEqual({snapshot.revision for snapshot in result.values()}, {1})
        self.assertEqual(SettingsChange.objects.count(), 2)

    def test_protected_document_can_save_and_rollback_as_single_candidate(self):
        role, workflow, colors, registry = self._security_slice()
        repository = ConfigDocumentRepository(registry)
        writer = ConfigDocumentWriter(registry)
        current = repository.get_snapshot(
            (role.document_id, workflow.document_id, colors.document_id)
        )
        role_before = current[role.document_id]
        candidate = self._changed_role(role_before.payload, " — тест")

        applied = writer.save_document_via_domain_workflow(
            actor=self.actor,
            document_id=role.document_id,
            payload=candidate,
            expected_revision=role_before.revision,
            expected_content_hash=role_before.content_hash,
            authorize=lambda actor: None,
        )
        source = SettingsChange.objects.get(document_revision_after=1)
        restored = writer.rollback_document(
            actor=self.actor,
            document_id=role.document_id,
            source_change_id=source.pk,
            expected_revision=applied.revision,
            expected_content_hash=applied.content_hash,
            authorize=lambda actor: None,
        )

        self.assertEqual(restored.payload, role_before.payload)
        self.assertEqual(restored.revision, 2)
        self.assertFalse(
            RuntimeSettingDocument.objects.filter(
                document_id__in=(workflow.document_id, colors.document_id)
            ).exists()
        )

    def test_domain_rollback_rechecks_permission_after_lock(self):
        role, workflow, colors, registry = self._security_slice()
        repository = ConfigDocumentRepository(registry)
        writer = ConfigDocumentWriter(registry)
        current = repository.get_snapshot(
            (role.document_id, workflow.document_id, colors.document_id)
        )
        role_before = current[role.document_id]
        applied = writer.save_document_via_domain_workflow(
            actor=self.actor,
            document_id=role.document_id,
            payload=self._changed_role(role_before.payload, " — тест"),
            expected_revision=role_before.revision,
            expected_content_hash=role_before.content_hash,
            authorize=lambda actor: None,
        )
        source = SettingsChange.objects.get(document_revision_after=1)
        original_acquire = writer._acquire_locks

        def acquire_then_revoke(document_ids):
            original_acquire(document_ids)
            User.objects.filter(pk=self.actor.pk).update(
                is_superuser=False,
                is_staff=False,
            )

        with patch.object(writer, "_acquire_locks", side_effect=acquire_then_revoke):
            with self.assertRaises(PermissionDenied):
                writer.rollback_document(
                    actor=self.actor,
                    document_id=role.document_id,
                    source_change_id=source.pk,
                    expected_revision=applied.revision,
                    expected_content_hash=applied.content_hash,
                    authorize=lambda actor: None,
                )

        self.assertEqual(RuntimeSettingDocument.objects.get().revision, 1)
        self.assertEqual(SettingsChange.objects.count(), 1)

    def test_two_cross_document_writers_do_not_deadlock_or_mix_slices(self):
        workflow = replace(
            _database_spec("core.contract.workflow_rules"),
            write_policy="requires_domain_workflow",
        )
        colors = _database_spec("workorders.contract.status_colors")
        registry = _registry(workflow, colors)
        current = ConfigDocumentRepository(registry).get_snapshot(
            (workflow.document_id, colors.document_id)
        )
        candidates_by_tag = {}
        for tag, color, index in (("a", "#111111", 0), ("b", "#222222", 1)):
            workflow_payload = self._changed_workflow(
                current[workflow.document_id].payload,
                remove_index=index,
            )
            colors_payload = deepcopy(current[colors.document_id].payload)
            first_status = next(iter(colors_payload["statuses"]))
            colors_payload["statuses"][first_status]["color"] = color
            candidates_by_tag[tag] = {
                workflow.document_id: workflow_payload,
                colors.document_id: colors_payload,
            }
        expected = {
            document_id: ExpectedDocumentVersion(snapshot.revision, snapshot.content_hash)
            for document_id, snapshot in current.items()
        }
        barrier = Barrier(2)
        outcomes = []

        def write(tag):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                actor = User.objects.get(pk=self.actor.pk)
                ConfigDocumentWriter(registry).save_documents_via_domain_workflow(
                    actor=actor,
                    candidates=candidates_by_tag[tag],
                    expected=expected,
                    authorize=lambda actor: None,
                )
                outcomes.append(("success", tag))
            except DocumentWriteConflict:
                outcomes.append(("conflict", tag))
            finally:
                connections.close_all()

        threads = [Thread(target=write, args=(tag,)) for tag in candidates_by_tag]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sorted(item[0] for item in outcomes), ["conflict", "success"])
        winner = next(tag for outcome, tag in outcomes if outcome == "success")
        rows = RuntimeSettingDocument.objects.in_bulk()
        self.assertEqual(
            rows[workflow.document_id].payload,
            candidates_by_tag[winner][workflow.document_id],
        )
        self.assertEqual(
            rows[colors.document_id].payload,
            candidates_by_tag[winner][colors.document_id],
        )
        self.assertEqual(SettingsChange.objects.count(), 2)

    def test_same_fingerprint_on_unrelated_documents_is_typed_conflict(self):
        waiting = self.spec
        chat = _database_spec("ai.contract.chat_settings")
        registry = _registry(waiting, chat)
        current = ConfigDocumentRepository(registry).get_snapshot(
            (waiting.document_id, chat.document_id)
        )
        waiting_payload = deepcopy(current[waiting.document_id].payload)
        waiting_payload["statuses"]["waiting"]["color"] = "#123456"
        chat_payload = deepcopy(current[chat.document_id].payload)
        chat_payload["defaults"]["recent_message_limit"] += 1
        candidates = {
            waiting.document_id: waiting_payload,
            chat.document_id: chat_payload,
        }
        barrier = Barrier(2)
        outcomes = []

        def write(document_id):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                actor = User.objects.get(pk=self.actor.pk)
                snapshot = current[document_id]
                ConfigDocumentWriter(registry).save_document(
                    actor=actor,
                    document_id=document_id,
                    payload=candidates[document_id],
                    expected_revision=snapshot.revision,
                    expected_content_hash=snapshot.content_hash,
                    operation_fingerprint="same-fingerprint",
                )
                outcomes.append("success")
            except DocumentWriteConflict:
                outcomes.append("conflict")
            finally:
                connections.close_all()

        threads = [Thread(target=write, args=(document_id,)) for document_id in candidates]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ["success", "conflict"])
        self.assertEqual(RuntimeSettingDocument.objects.count(), 1)
        self.assertEqual(SettingsChange.objects.count(), 1)
