import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.core.models import Department
from apps.warehouse.legacy_import.landing import LandingPackageError, load_landing_package, write_landing_package
from apps.warehouse.legacy_import.services import (
    LegacyImportError,
    _validate_rows,
    ensure_import_run,
    import_landing,
    reconcile_landing,
)
from apps.warehouse.models import (
    FundingSource,
    StockBalance,
    StockDocument,
    WarehouseImportRecord,
    WarehouseItem,
)


class LegacyLandingPackageTests(SimpleTestCase):
    def test_landing_package_masks_secret_fields_and_verifies_jsonl(self):
        run_id = str(uuid.uuid4())
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            target, manifest = write_landing_package(
                run_id=run_id,
                source_fingerprint="a" * 64,
                source_name=r"C:\private\uls.mdb",
                adapter="access-v1",
                transformation_version="access-v1.0",
                tables={"s_otdelenie": [{"otd_name": "Тест", "pass": "never-write", "token_value": "never-write"}]},
            )
            _, loaded_manifest, rows = load_landing_package(run_id)

        self.assertEqual(target.name, run_id)
        self.assertEqual(manifest["source_name"], "uls.mdb")
        self.assertEqual(loaded_manifest["tables"][0]["row_count"], 1)
        self.assertEqual(rows["s_otdelenie"][0]["payload"], {"otd_name": "Тест"})

    def test_package_rejects_path_outside_data_or_local_and_duplicate_rows(self):
        run_id = str(uuid.uuid4())
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside, self.settings(DATA_DIR=Path(tmpdir)):
            with self.assertRaises(LandingPackageError):
                write_landing_package(
                    run_id=run_id,
                    source_fingerprint="b" * 64,
                    source_name="source.mdb",
                    adapter="access-v1",
                    transformation_version="access-v1.0",
                    tables={},
                    requested_dir=Path(outside) / run_id,
                )
            with self.assertRaises(LandingPackageError):
                write_landing_package(
                    run_id=run_id,
                    source_fingerprint="b" * 64,
                    source_name="source.mdb",
                    adapter="access-v1",
                    transformation_version="access-v1.0",
                    tables={"s_ls": [{"name": "Одинаково"}, {"name": "Одинаково"}]},
                )

    def test_unknown_unit_is_critical_prepare_issue(self):
        rows = {"s_ls": [{"payload": {"name": "Тест", "unit": "неизвестно"}, "row_hash": "x"}]}
        issues = _validate_rows(rows=rows, mapping={"units": {}}, include_unused_catalog=True)
        self.assertTrue(any(issue.code == "unit_mapping_missing" and issue.severity == "critical" for issue in issues))

    def test_conflicting_expiry_for_normalized_series_is_critical(self):
        rows = {
            "istoch": [{"payload": {"name": "Бюджет"}, "row_hash": "source"}],
            "s_ls": [
                {"payload": {"name": "Марля", "unit": "шт"}, "row_hash": "item"}
            ],
            "stelazh": [
                {
                    "payload": {
                        "department": "Отделение",
                        "item": "Марля",
                        "unit": "шт",
                        "funding_source": "Бюджет",
                        "quantity": "1",
                        "batch": " A   1 ",
                        "expires_on": "2027-01-01",
                    },
                    "row_hash": "balance-1",
                },
                {
                    "payload": {
                        "department": "Отделение",
                        "item": "Марля",
                        "unit": "шт",
                        "funding_source": "Бюджет",
                        "quantity": "1",
                        "batch": "a 1",
                        "expires_on": "2028-01-01",
                    },
                    "row_hash": "balance-2",
                },
            ],
        }
        issues = _validate_rows(
            rows=rows,
            mapping={
                "departments": {"Отделение": "1"},
                "units": {"шт": "шт"},
                "opening_date": "2026-01-01",
            },
            include_unused_catalog=True,
        )
        conflicts = [issue for issue in issues if issue.code == "series_expiry_conflict"]
        self.assertEqual(len(conflicts), 2)
        self.assertTrue(all(issue.severity == "critical" for issue in conflicts))

    def test_code_identity_drives_conflict_without_using_display_name_as_code(self):
        rows = {
            "istoch": [
                {
                    "payload": {"kod": "SRC-01", "name": "Основной источник"},
                    "row_hash": "source-1",
                },
                {
                    "payload": {"kod": "SRC-02", "name": "Другой источник"},
                    "row_hash": "source-2",
                },
            ],
            "s_ls": [
                {
                    "payload": {"kod": "MED-02", "name": "Марля", "unit": "шт"},
                    "row_hash": "item-2",
                },
                {
                    "payload": {
                        "kod": "MED-10",
                        "name": "Бинт",
                        "unit": "шт",
                    },
                    "row_hash": "item-10",
                },
            ],
            "stelazh": [
                {
                    "payload": {
                        "department": "Отделение",
                        "item_code": "MED-02",
                        "item": "Старое название 1",
                        "unit": "шт",
                        "funding_source_code": "SRC-01",
                        "funding_source": "Старое название источника",
                        "quantity": "1",
                        "batch": "CODE-SERIES",
                        "expires_on": "2027-01-01",
                    },
                    "row_hash": "balance-code-1",
                },
                {
                    "payload": {
                        "department": "Отделение",
                        "item_code": "MED-02",
                        "item": "Старое название 2",
                        "unit": "шт",
                        "funding_source_code": "SRC-01",
                        "funding_source": "Другое старое название",
                        "quantity": "1",
                        "batch": "code-series",
                        "expires_on": "2028-01-01",
                    },
                    "row_hash": "balance-code-2",
                },
                {
                    "payload": {
                        "department": "Отделение",
                        "item_code": "MED-10",
                        "item": "Не имя из каталога",
                        "unit": "шт",
                        "funding_source_code": "SRC-02",
                        "funding_source": "Не имя источника из каталога",
                        "quantity": "1",
                        "batch": "CODE-SERIES",
                        "expires_on": "2029-01-01",
                    },
                    "row_hash": "balance-code-3",
                },
            ],
        }
        issues = _validate_rows(
            rows=rows,
            mapping={
                "departments": {"Отделение": "1"},
                "units": {"шт": "шт"},
                "opening_date": "2026-01-01",
            },
            include_unused_catalog=True,
        )

        conflicts = [issue for issue in issues if issue.code == "series_expiry_conflict"]
        self.assertEqual(len(conflicts), 2)
        self.assertEqual(
            {issue.context["item_code"] for issue in conflicts},
            {"legacy-item-med-02"},
        )
        self.assertFalse(
            any(
                issue.code
                in {
                    "opening_item_missing",
                    "opening_funding_source_missing",
                }
                for issue in issues
            )
        )


class LegacyImportIdempotencyTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Тестовое отделение")
        self.actor = get_user_model().objects.create_superuser(
            username="warehouse-legacy-root", password="pass", department=self.department
        )
        self.run_id = str(uuid.uuid4())
        self.mapping = {
            "departments": {"Тестовое отделение": str(self.department.pk)},
            "units": {"шт": "шт"},
            "opening_date": "2026-08-31",
        }

    def _write_package(self, data_dir: Path):
        return write_landing_package(
            run_id=self.run_id,
            source_fingerprint="c" * 64,
            source_name="synthetic.mdb",
            adapter="access-v1",
            transformation_version="access-v1.0",
            tables={
                "s_otdelenie": [{"otd_name": "Тестовое отделение"}],
                "istoch": [{"kod": "SRC-77", "name": "Бюджет"}],
                "s_ls": [{"kod": "MED-42", "name": "Марля", "unit": "шт"}],
                "stelazh": [
                    {
                        "department": "Тестовое отделение",
                        "item_code": "MED-42",
                        "item": "Старое имя позиции",
                        "unit": "шт",
                        "funding_source_code": "SRC-77",
                        "funding_source": "Старое имя источника",
                        "quantity": "3",
                        "batch": "A-1",
                    }
                ],
                "Sklad": [
                    {
                        "department": "Тестовое отделение",
                        "item_code": "MED-42",
                        "item": "Отчётное имя позиции",
                        "unit": "шт",
                        "funding_source_code": "SRC-77",
                        "funding_source": "Отчётное имя источника",
                        "quantity": "3",
                    }
                ],
                "uchet": [],
            },
        )

    def test_commit_is_idempotent_and_uses_posted_opening_document(self):
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            self._write_package(Path(tmpdir))
            preview = import_landing(run_id=self.run_id, mapping=self.mapping, commit=False)
            first = import_landing(run_id=self.run_id, mapping=self.mapping, commit=True, actor=self.actor)
            second = import_landing(run_id=self.run_id, mapping=self.mapping, commit=True, actor=self.actor)

            self.assertTrue(preview["ok"])
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(FundingSource.objects.count(), 1)
            self.assertEqual(WarehouseItem.objects.count(), 1)
            self.assertEqual(FundingSource.objects.get().code, "legacy-source-src-77")
            self.assertEqual(FundingSource.objects.get().name, "Бюджет")
            self.assertEqual(WarehouseItem.objects.get().code, "legacy-item-med-42")
            self.assertEqual(WarehouseItem.objects.get().name, "Марля")
            self.assertEqual(StockDocument.objects.filter(document_type="opening", status="posted").count(), 1)
            self.assertEqual(StockBalance.objects.count(), 1)
            self.assertEqual(StockBalance.objects.get().quantity, 3)
            self.assertEqual(WarehouseImportRecord.objects.filter(source_table="stelazh").count(), 1)

            self.assertTrue(reconcile_landing(run_id=self.run_id, strict=True)["ok"])
            StockBalance.objects.update(quantity=2)
            mismatch = reconcile_landing(run_id=self.run_id, strict=True)
            self.assertFalse(mismatch["ok"])
            self.assertEqual(len(mismatch["balance_mismatches"]), 1)

    def test_same_source_cannot_be_registered_under_another_run_id(self):
        manifest = {
            "run_id": self.run_id,
            "source_fingerprint": "d" * 64,
            "source_name": "synthetic.mdb",
            "adapter": "access-v1",
            "transformation_version": "access-v1.0",
        }
        first = ensure_import_run(manifest=manifest)
        with self.assertRaises(LegacyImportError):
            ensure_import_run(
                manifest={**manifest, "run_id": str(uuid.uuid4())}
            )
        self.assertEqual(first.run_id, uuid.UUID(self.run_id))
pytestmark = pytest.mark.integration
