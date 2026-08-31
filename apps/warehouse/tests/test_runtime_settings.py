import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from apps.warehouse.contracts import validate_warehouse_settings_payload
from apps.warehouse.runtime_settings import get_warehouse_runtime_settings


class WarehouseSettingsValidationTests(TestCase):
    def test_default_payload_is_valid(self):
        self.assertEqual(validate_warehouse_settings_payload({"default_quantity_precision": 0, "expiry_warning_days": [30, 90]})["default_quantity_precision"], 0)

    def test_rejects_invalid_precision_and_threshold_order(self):
        with self.assertRaises(Exception):
            validate_warehouse_settings_payload({"default_quantity_precision": 7, "expiry_warning_days": [30]})
        with self.assertRaises(Exception):
            validate_warehouse_settings_payload({"default_quantity_precision": 0, "expiry_warning_days": [90, 30]})


class WarehouseRuntimeSettingsTests(TestCase):
    def test_reads_runtime_json_before_git_default(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"default_quantity_precision": 2, "expiry_warning_days": [10, 20]}), encoding="utf-8")
            with override_settings(WAREHOUSE_RUNTIME_SETTINGS_FILE=path):
                self.assertEqual(get_warehouse_runtime_settings()["default_quantity_precision"], 2)

    def test_repository_is_preferred_without_writing(self):
        fake = type("Repository", (), {"get_document": staticmethod(lambda document_id, request=None: {"payload": {"default_quantity_precision": 1, "expiry_warning_days": [7]}})})
        with patch("apps.warehouse.runtime_settings.importlib.import_module", return_value=fake):
            self.assertEqual(get_warehouse_runtime_settings()["expiry_warning_days"], [7])

    def test_missing_repository_document_falls_back_to_file_contract(self):
        fake = type(
            "Repository",
            (),
            {
                "get_document": staticmethod(
                    lambda document_id, request=None: (_ for _ in ()).throw(
                        LookupError(document_id)
                    )
                )
            },
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "default_quantity_precision": 3,
                        "expiry_warning_days": [15],
                    }
                ),
                encoding="utf-8",
            )
            with override_settings(WAREHOUSE_RUNTIME_SETTINGS_FILE=path), patch(
                "apps.warehouse.runtime_settings.importlib.import_module",
                return_value=fake,
            ):
                self.assertEqual(
                    get_warehouse_runtime_settings()["default_quantity_precision"],
                    3,
                )
