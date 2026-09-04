"""Независимые проверки пилота хранения палитры листа ожидания в БД.

Тесты намеренно не исправляют production-код: если отдельный срез ещё не
переключён или нарушает контракт, это должно быть видно как явное падение.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

import pytest
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.contract_store import get_contract, registered_contracts
from apps.settings_center.contract_services import rollback_contract_change
from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import ConfigDocumentRepository
from apps.settings_center.document_services import (
    ConfigDocumentWriter,
    DocumentWriteError,
)
from apps.settings_center.models import RuntimeSettingDocument, SettingsChange
from apps.settings_center.registry import get_registry


DOCUMENT_ID = "waiting_list.contract.status_colors"


def _clear_settings_caches():
    get_document_registry.cache_clear()
    get_registry.cache_clear()
    from apps.core import contract_store

    contract_store._reset_for_tests()


@pytest.mark.integration
class WaitingStatusColorsPilotTests(TestCase):
    """SQLite: routing, request freshness, fallback and legacy isolation."""

    def setUp(self):
        super().setUp()
        _clear_settings_caches()
        self.addCleanup(_clear_settings_caches)
        self.user = get_user_model().objects.create_superuser(
            username="settings-pilot",
            email="settings-pilot@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.default = ConfigDocumentRepository().get_document(DOCUMENT_ID)

    def test_allowlist_routes_waiting_document_to_database_and_unknown_is_rejected(self):
        self.assertEqual(
            get_document_registry().get(DOCUMENT_ID).active_backend,
            "legacy_file",
        )
        with override_settings(
            LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(DOCUMENT_ID,)
        ):
            _clear_settings_caches()
            self.assertEqual(
                get_document_registry().get(DOCUMENT_ID).active_backend,
                "database",
            )
            snapshot = ConfigDocumentRepository().get_document(DOCUMENT_ID)
            self.assertEqual(snapshot.source, "git_default")
            self.assertEqual(snapshot.revision, 0)
            self.assertNotIn("waiting_list_status_colors", registered_contracts())
            self.assertIn("workorder_status_colors", registered_contracts())

        with override_settings(
            LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=("not.released",)
        ):
            _clear_settings_caches()
            with self.assertRaises(ValueError):
                get_document_registry()

    @override_settings(
        LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(DOCUMENT_ID,)
    )
    def test_get_contract_uses_database_default_and_request_snapshot_is_fresh(self):
        _clear_settings_caches()
        request = self.client.get("/").wsgi_request
        first = get_contract("waiting_list_status_colors", request=request)
        self.assertEqual(first, self.default.payload)
        changed = deepcopy(self.default.payload)
        changed["statuses"]["waiting"]["color"] = "#123456"
        RuntimeSettingDocument.objects.create(
            document_id=DOCUMENT_ID,
            schema_version=self.default.schema_version,
            payload=changed,
            revision=1,
            content_hash=document_hash(changed),
            default_hash=self.default.default_hash,
        )
        self.assertEqual(
            get_contract("waiting_list_status_colors", request=request), first
        )
        second = get_contract("waiting_list_status_colors")
        self.assertEqual(second["statuses"]["waiting"]["color"], "#123456")

    def test_legacy_workorders_contract_remains_file_backed(self):
        original = get_contract("workorder_status_colors")
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "workorder-status.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE=str(path),
                LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(DOCUMENT_ID,),
            ):
                _clear_settings_caches()
                descriptor = get_registry().get("workorders.contract.status_colors")
                self.assertEqual(descriptor.metadata["active_backend"], "legacy_file")
                self.assertEqual(
                    get_document_registry().get(
                        "workorders.contract.status_colors"
                    ).active_backend,
                    "legacy_file",
                )
                self.assertEqual(get_contract("workorder_status_colors"), original)

    @override_settings(
        LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(DOCUMENT_ID,)
    )
    def test_waiting_list_view_renders_configured_colors(self):
        _clear_settings_caches()
        payload = deepcopy(self.default.payload)
        payload["statuses"]["waiting"].update(
            color="#123456", background="#abcdef"
        )
        RuntimeSettingDocument.objects.create(
            document_id=DOCUMENT_ID,
            schema_version=self.default.schema_version,
            payload=payload,
            revision=1,
            content_hash=document_hash(payload),
            default_hash=self.default.default_hash,
        )
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "#123456")
        self.assertContains(response, "#abcdef")


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
@override_settings(
    LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(DOCUMENT_ID,)
)
@pytest.mark.integration
class WaitingStatusColorsPostgresPilotTests(TestCase):
    """PostgreSQL: UI writer, optimistic concurrency, independent reads/rollback."""

    def setUp(self):
        super().setUp()
        _clear_settings_caches()
        self.addCleanup(_clear_settings_caches)
        self.user = get_user_model().objects.create_superuser(
            username="settings-pilot-pg",
            email="settings-pilot-pg@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.default = ConfigDocumentRepository().get_document(DOCUMENT_ID)

    def _changed(self, color):
        payload = deepcopy(self.default.payload)
        payload["statuses"]["waiting"]["color"] = color
        return payload

    def test_ui_post_creates_revision_and_does_not_rewrite_legacy_file(self):
        with TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "waiting-status.json"
            legacy_path.write_text(json.dumps(self.default.payload), encoding="utf-8")
            before = legacy_path.read_bytes()
            with override_settings(
                LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS_FILE=str(legacy_path),
            ):
                response = self.client.get(reverse("settings_center:waiting_list_status_colors"))
                self.assertEqual(response.status_code, 200)
                payload = self._changed("#123456")
                response = self.client.post(
                    reverse("settings_center:waiting_list_status_colors"),
                    {
                        "confirm": "on",
                        "base_hash": self.default.content_hash,
                        "base_revision": "0",
                        **{
                            f"color__{code}": config["color"]
                            for code, config in payload["statuses"].items()
                        },
                        **{
                            f"background__{code}": config["background"]
                            for code, config in payload["statuses"].items()
                        },
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(legacy_path.read_bytes(), before)
        self.assertEqual(response.status_code, 302)
        row = RuntimeSettingDocument.objects.get(document_id=DOCUMENT_ID)
        self.assertEqual(row.revision, 1)
        self.assertEqual(
            SettingsChange.objects.filter(
                setting_id=DOCUMENT_ID, storage_kind="runtime_document"
            ).count(),
            1,
        )

    def test_stale_write_conflicts_and_independent_repository_sees_revision(self):
        changed = self._changed("#123456")
        first = ConfigDocumentWriter().save_document(
            actor=self.user,
            document_id=DOCUMENT_ID,
            payload=changed,
            expected_revision=0,
            expected_content_hash=self.default.content_hash,
        )
        self.assertEqual(ConfigDocumentRepository().get_document(DOCUMENT_ID).revision, 1)
        with self.assertRaises(Exception) as caught:
            ConfigDocumentWriter().save_document(
                actor=self.user,
                document_id=DOCUMENT_ID,
                payload=self._changed("#654321"),
                expected_revision=0,
                expected_content_hash=self.default.content_hash,
            )
        self.assertIn("измен", str(caught.exception).lower())
        self.assertEqual(first.change_id, SettingsChange.objects.latest("id").pk)

    def test_rollback_creates_second_revision_and_audit(self):
        changed = self._changed("#123456")
        first = ConfigDocumentWriter().save_document(
            actor=self.user,
            document_id=DOCUMENT_ID,
            payload=changed,
            expected_revision=0,
            expected_content_hash=self.default.content_hash,
        )
        current = ConfigDocumentRepository().get_document(DOCUMENT_ID)
        rollback = rollback_contract_change(
            actor=self.user,
            change_id=first.change_id,
            confirmed=True,
            base_hash=current.content_hash,
            base_revision=current.revision,
        )
        self.assertEqual(RuntimeSettingDocument.objects.get(pk=DOCUMENT_ID).revision, 2)
        self.assertEqual(rollback.action, SettingsChange.Action.ROLLBACK)
        self.assertEqual(
            SettingsChange.objects.filter(
                setting_id=DOCUMENT_ID, storage_kind="runtime_document"
            ).count(),
            2,
        )

    def test_corrupt_row_is_visible_fallback_and_post_is_refused(self):
        RuntimeSettingDocument.objects.create(
            document_id=DOCUMENT_ID,
            schema_version=self.default.schema_version,
            payload=self.default.payload,
            revision=1,
            content_hash="0" * 64,
            default_hash=self.default.default_hash,
        )
        snapshot = ConfigDocumentRepository().get_document(DOCUMENT_ID)
        self.assertEqual(snapshot.source, "git_default_fallback")
        self.assertTrue(snapshot.degraded)
        response = self.client.get(
            reverse("settings_center:waiting_list_status_colors")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Показан Git-дефолт")
        with self.assertRaises(DocumentWriteError):
            ConfigDocumentWriter().save_document(
                actor=self.user,
                document_id=DOCUMENT_ID,
                payload=self._changed("#123456"),
                expected_revision=1,
                expected_content_hash="0" * 64,
            )
        self.assertEqual(SettingsChange.objects.filter(setting_id=DOCUMENT_ID).count(), 0)
