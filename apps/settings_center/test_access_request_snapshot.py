"""Request-local consistency checks for the connected access documents."""

from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.services import apply_role_assignment, preview_role_assignment
from apps.core.contract_store import get_contract
from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import (
    ConfigDocumentRepository,
    DocumentRepositoryError,
    get_active_repository,
)
from apps.settings_center.models import RuntimeSettingDocument
from apps.settings_center.registry import get_registry
from apps.workorders.models import Board

pytestmark = pytest.mark.integration


DOCUMENT_IDS = (
    "core.contract.role_rules",
    "core.contract.workflow_rules",
    "workorders.contract.status_colors",
)


def clear_settings_caches():
    get_document_registry.cache_clear()
    get_registry.cache_clear()
    from apps.core import contract_store

    contract_store._reset_for_tests()


@override_settings(LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=DOCUMENT_IDS)
class AccessRequestSnapshotTests(TestCase):
    """SQLite covers lifecycle and request consistency without a new database."""

    def setUp(self):
        super().setUp()
        clear_settings_caches()
        self.addCleanup(clear_settings_caches)
        self.defaults = ConfigDocumentRepository().get_snapshot(DOCUMENT_IDS)

    def _create_revision(self, document_id, marker, revision=1):
        payload = deepcopy(self.defaults[document_id].payload)
        if document_id == "core.contract.role_rules":
            payload["manager"]["display_name"] = marker
        else:
            payload["__test_marker"] = marker
        RuntimeSettingDocument.objects.create(
            document_id=document_id,
            schema_version=self.defaults[document_id].schema_version,
            payload=payload,
            revision=revision,
            content_hash=document_hash(payload),
            default_hash=self.defaults[document_id].default_hash,
        )

    def _update_revision(self, document_id, marker, revision=2):
        row = RuntimeSettingDocument.objects.get(document_id=document_id)
        payload = deepcopy(row.payload)
        if document_id == "core.contract.role_rules":
            payload["manager"]["display_name"] = marker
        else:
            payload["__test_marker"] = marker
        row.payload = payload
        row.revision = revision
        row.content_hash = document_hash(payload)
        row.save(update_fields=["payload", "revision", "content_hash", "updated_at"])

    def test_requestless_calls_share_connected_snapshot_and_next_request_refreshes(self):
        for document_id in DOCUMENT_IDS:
            self._create_revision(document_id, "v1")

        first_request = RequestFactory().get("/")

        def first_view(request):
            first_role = get_contract("role_rules")
            for document_id in DOCUMENT_IDS:
                self._update_revision(document_id, "v2")
            return (
                first_role["manager"]["display_name"],
                get_contract("workflow_rules")["__test_marker"],
                get_contract("workorder_status_colors")["__test_marker"],
            )

        response = self._middleware(first_view)(first_request)
        self.assertEqual(response, ("v1", "v1", "v1"))
        self.assertIsNone(get_active_repository())

        second_request = RequestFactory().get("/")
        self.assertEqual(
            self._middleware(
                lambda request: (
                    get_contract("role_rules")["manager"]["display_name"],
                    get_contract("workflow_rules")["__test_marker"],
                    get_contract("workorder_status_colors")["__test_marker"],
                )
            )(second_request),
            ("v2", "v2", "v2"),
        )

    def test_exception_clears_request_context(self):
        request = RequestFactory().get("/")

        def failing_view(request):
            get_contract("role_rules")
            raise RuntimeError("expected test failure")

        with self.assertRaises(RuntimeError):
            self._middleware(failing_view)(request)
        self.assertIsNone(get_active_repository())

    def test_outside_request_reads_fresh_database_revision(self):
        self._create_revision(DOCUMENT_IDS[0], "v1")
        self.assertEqual(get_contract("role_rules")["manager"]["display_name"], "v1")
        self._update_revision(DOCUMENT_IDS[0], "v2")
        self.assertEqual(get_contract("role_rules")["manager"]["display_name"], "v2")

    def test_assignment_preview_apply_rejects_role_revision_race_inside_stale_request(self):
        for document_id in DOCUMENT_IDS:
            self._create_revision(document_id, "v1")
        actor = get_user_model().objects.create_superuser(username="snapshot-race-admin")
        target = get_user_model().objects.create_user(username="snapshot-race-target")
        Group.objects.get_or_create(name="customer")
        request = RequestFactory().get("/")

        def view(_request):
            # Prime the regular request snapshot, then let a concurrent writer
            # advance the DB row before the signed plan is applied.
            self.assertEqual(get_contract("role_rules")["manager"]["display_name"], "v1")
            preview = preview_role_assignment(
                actor=actor,
                target_user=target,
                selected_role_names=["customer"],
            )
            signed = signing.loads(
                preview["preview_token"],
                salt="accounts.access-assignment-preview.v2",
                max_age=None,
            )
            self.assertIn("role_contract_hash", signed)
            self.assertIn("role_contract_revision", signed)
            self._update_revision("core.contract.role_rules", "v2")
            with self.assertRaises(ValidationError):
                apply_role_assignment(
                    actor=actor,
                    target_user=target,
                    selected_role_names=["customer"],
                    preview_token=preview["preview_token"],
                    risk_confirmed=True,
                )
            return None

        self._middleware(view)(request)

    def test_role_materialization_repair_reloads_db_after_stale_request_snapshot(self):
        from apps.accounts.access_contracts import _new_role_config, save_role_creation
        from apps.core.file_locks import exclusive_file_lock as real_exclusive_file_lock
        from apps.settings_center.contract_services import read_contract_snapshot

        role_document_id = "core.contract.role_rules"
        role_payload = deepcopy(self.defaults[role_document_id].payload)
        role_code = "repair_race_role"
        role_config = _new_role_config(
            role_code=role_code,
            display_name="Роль v1",
            description="Материализация после гонки",
            protected=False,
            catalog=role_payload["$capabilities"],
        )
        role_payload[role_code] = role_config
        RuntimeSettingDocument.objects.create(
            document_id=role_document_id,
            schema_version=self.defaults[role_document_id].schema_version,
            payload=role_payload,
            revision=1,
            content_hash=document_hash(role_payload),
            default_hash=self.defaults[role_document_id].default_hash,
        )
        actor = get_user_model().objects.create_superuser(
            username="repair-race-admin",
            password="test-password",
        )
        request = RequestFactory().get("/")

        def advance_role_document_before_lock(path, *, timeout=10.0, poll_interval=0.05):
            @contextmanager
            def locked():
                row = RuntimeSettingDocument.objects.get(document_id=role_document_id)
                changed_payload = deepcopy(row.payload)
                # Keep the target role unchanged: the rejection must be caused
                # by the fresh document's revision/hash, not by a changed
                # expected role config.
                changed_payload["manager"]["display_name"] = "Менеджер v2"
                row.payload = changed_payload
                row.revision = 2
                row.content_hash = document_hash(changed_payload)
                row.save(update_fields=["payload", "revision", "content_hash", "updated_at"])
                with real_exclusive_file_lock(
                    path, timeout=timeout, poll_interval=poll_interval
                ) as held:
                    yield held

            return locked()

        def view(_request):
            stale = read_contract_snapshot(
                get_registry().get(role_document_id), request=request
            )
            self.assertEqual(stale.revision, 1)
            with patch(
                "apps.accounts.access_contracts.exclusive_file_lock",
                side_effect=advance_role_document_before_lock,
            ), self.assertRaisesRegex(ValidationError, "Контракт роли изменился"):
                save_role_creation(
                    actor=actor,
                    role_code=role_code,
                    display_name="Роль v1",
                    description="Материализация после гонки",
                    protected=False,
                    base_hash=stale.content_hash,
                    base_revision=stale.revision,
                )

            self.assertFalse(Group.objects.filter(name=role_code).exists())
            current = RuntimeSettingDocument.objects.get(document_id=role_document_id)
            self.assertNotEqual(current.revision, stale.revision)
            self.assertNotEqual(current.content_hash, stale.content_hash)
            self.assertEqual(current.revision, 2)
            self.assertEqual(current.payload["manager"]["display_name"], "Менеджер v2")
            self.assertEqual(current.payload[role_code], role_config)

        self._middleware(view)(request)

    def test_role_ui_hides_repository_error_as_opaque_503(self):
        actor = get_user_model().objects.create_superuser(username="settings-ui-error-admin")
        self.client.force_login(actor)
        with patch(
            "apps.settings_center.views.role_catalog_rows",
            side_effect=DocumentRepositoryError("payload=/private/runtime/role_rules.json"),
        ):
            response = self.client.get(reverse("settings_center:role_catalog"))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private/runtime", response.content.decode())
        self.assertNotIn("role_rules.json", response.content.decode())

    def test_setting_detail_repository_error_is_opaque_503(self):
        actor = get_user_model().objects.create_superuser(
            username="settings-detail-error-admin"
        )
        self.client.force_login(actor)
        with patch(
            "apps.settings_center.views.read_contract_snapshot",
            side_effect=DocumentRepositoryError("payload=/private/runtime/role_rules.json"),
        ):
            response = self.client.get(
                reverse(
                    "settings_center:setting_detail",
                    kwargs={"setting_id": "workorders.contract.status_colors"},
                )
            )
        self.assertEqual(response.status_code, 503)
        body = response.content.decode()
        self.assertEqual(body, "Конфигурация временно недоступна.")
        self.assertNotIn("private/runtime", body)
        self.assertNotIn("role_rules.json", body)

    def test_viewer_migration_rejects_database_backend_before_side_effects(self):
        from apps.settings_center import access_migration_services, document_registry

        fake_registry = SimpleNamespace(
            get=lambda document_id: SimpleNamespace(active_backend="database")
        )
        with patch.object(document_registry, "get_document_registry", return_value=fake_registry):
            with self.assertRaisesMessage(
                ValidationError,
                "access role_rules уже использует PostgreSQL",
            ):
                access_migration_services.prepare_explicit_viewer_migration(
                    actor=None,
                    manifest={},
                    reason="test",
                )

    def test_viewer_cutover_and_rollback_reject_db_backend_without_partial_changes(self):
        from apps.settings_center import access_migration_services, document_registry

        target = get_user_model().objects.create_user(username="viewer-db-guard-target")
        customer, _ = Group.objects.get_or_create(name="customer")
        target.groups.add(customer)
        board = Board.objects.create(title="DB guard board", slug="viewer-db-guard")
        board.allowed_groups.add(customer)
        before_groups = set(target.groups.values_list("name", flat=True))
        before_board_groups = set(board.allowed_groups.values_list("name", flat=True))
        prepared_legacy_manifest = {
            "schema_version": 1,
            "prepared": True,
            "cutover": True,
        }
        fake_registry = SimpleNamespace(
            get=lambda document_id: SimpleNamespace(active_backend="database")
        )

        for operation in (
            access_migration_services.cutover_explicit_viewer,
            access_migration_services.rollback_explicit_viewer,
        ):
            with self.subTest(operation=operation.__name__):
                with patch.object(
                    document_registry,
                    "get_document_registry",
                    return_value=fake_registry,
                ), patch.object(
                    access_migration_services,
                    "_fresh_superuser",
                    side_effect=AssertionError("DB guard must run first"),
                ):
                    with self.assertRaisesMessage(
                        ValidationError,
                        "access role_rules уже использует PostgreSQL",
                    ):
                        operation(
                            actor=None,
                            manifest=prepared_legacy_manifest,
                            reason="test",
                        )

        self.assertEqual(
            set(target.groups.values_list("name", flat=True)), before_groups
        )
        self.assertEqual(
            set(board.allowed_groups.values_list("name", flat=True)),
            before_board_groups,
        )

    @staticmethod
    def _middleware(view):
        from apps.settings_center.middleware import ConfigDocumentRequestMiddleware

        return ConfigDocumentRequestMiddleware(view)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
@override_settings(LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=DOCUMENT_IDS)
class AccessRequestSnapshotPostgresTests(AccessRequestSnapshotTests):
    """PostgreSQL executes the same checks against JSONB runtime rows."""
