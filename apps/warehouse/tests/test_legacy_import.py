import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

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
                "istoch": [{"name": "Бюджет"}],
                "s_ls": [{"name": "Марля", "unit": "шт"}],
                "stelazh": [{"department": "Тестовое отделение", "item": "Марля", "unit": "шт", "funding_source": "Бюджет", "quantity": "3", "batch": "A-1"}],
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
