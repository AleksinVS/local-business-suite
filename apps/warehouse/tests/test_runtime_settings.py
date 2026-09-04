from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import TestCase, override_settings

from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import get_document
from apps.settings_center.models import RuntimeSettingDocument
from apps.settings_center.registry import get_registry
from apps.warehouse.contracts import validate_warehouse_settings_payload
from apps.warehouse.runtime_settings import (
    WAREHOUSE_SETTINGS_DOCUMENT_ID,
    get_warehouse_runtime_settings,
)


pytestmark = pytest.mark.unit


class WarehouseSettingsValidationTests(TestCase):
    def test_default_payload_is_valid(self):
        self.assertEqual(validate_warehouse_settings_payload({"default_quantity_precision": 0, "expiry_warning_days": [30, 90]})["default_quantity_precision"], 0)

    def test_rejects_invalid_precision_and_threshold_order(self):
        with self.assertRaises(Exception):
            validate_warehouse_settings_payload({"default_quantity_precision": 7, "expiry_warning_days": [30]})
        with self.assertRaises(Exception):
            validate_warehouse_settings_payload({"default_quantity_precision": 0, "expiry_warning_days": [90, 30]})


class WarehouseRuntimeSettingsTests(TestCase):
    def test_reads_repository_snapshot_without_writing(self):
        snapshot = SimpleNamespace(
            payload={"default_quantity_precision": 1, "expiry_warning_days": [7]}
        )
        with patch("apps.warehouse.runtime_settings.get_document", return_value=snapshot) as getter:
            self.assertEqual(get_warehouse_runtime_settings()["expiry_warning_days"], [7])
        getter.assert_called_once_with("warehouse.settings", request=None)

    def test_returns_a_copy_of_repository_payload(self):
        payload = {
            "default_quantity_precision": 3,
            "expiry_warning_days": [15],
        }
        snapshot = SimpleNamespace(payload=payload)
        with patch(
            "apps.warehouse.runtime_settings.get_document", return_value=snapshot
        ):
            result = get_warehouse_runtime_settings()
        result["expiry_warning_days"].append(30)
        self.assertEqual(payload["expiry_warning_days"], [15])


@override_settings(
    LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=(WAREHOUSE_SETTINGS_DOCUMENT_ID,)
)
class WarehouseRuntimeSettingsRepositoryTests(TestCase):
    def setUp(self):
        get_document_registry.cache_clear()
        get_registry.cache_clear()
        self.addCleanup(get_document_registry.cache_clear)
        self.addCleanup(get_registry.cache_clear)

    def test_reads_database_override_through_central_repository(self):
        default = get_document(WAREHOUSE_SETTINGS_DOCUMENT_ID)
        payload = {
            "default_quantity_precision": 2,
            "expiry_warning_days": [10, 20],
        }
        RuntimeSettingDocument.objects.create(
            document_id=WAREHOUSE_SETTINGS_DOCUMENT_ID,
            schema_version=default.schema_version,
            payload=payload,
            revision=1,
            content_hash=document_hash(payload),
            default_hash=default.default_hash,
        )

        self.assertEqual(get_warehouse_runtime_settings(), payload)
