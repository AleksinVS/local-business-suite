from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest
from django.conf import settings
from django.test import SimpleTestCase


class InlineSeriesMigrationTests(SimpleTestCase):
    def _run_scenario(self, scenario):
        local_dir = Path(settings.BASE_DIR) / ".local"
        local_dir.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).with_name("inline_series_migration_scenario.py")
        with TemporaryDirectory(dir=local_dir) as temporary:
            temporary_path = Path(temporary)
            environment = os.environ.copy()
            environment.update(
                {
                    "DJANGO_SETTINGS_MODULE": "config.settings_test",
                    "LOCAL_BUSINESS_DB_BACKEND": "sqlite",
                    "LOCAL_BUSINESS_SQLITE_PATH": str(temporary_path / "migration.sqlite3"),
                    "LOCAL_BUSINESS_DATA_DIR": str(temporary_path / "data"),
                    "PYTHONPATH": str(settings.BASE_DIR),
                    "WAREHOUSE_INLINE_SERIES_SCENARIO": scenario,
                }
            )
            completed = subprocess.run(
                [sys.executable, str(script)],
                cwd=settings.BASE_DIR,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        return completed.stdout

    def test_expand_switch_reverse_and_contract_preserve_ledger(self):
        self.assertIn("migration e2e: OK", self._run_scenario("success"))

    def test_conflicting_expiry_aborts_expand_without_guessing(self):
        self.assertIn("conflict rollback: OK", self._run_scenario("conflict"))

    def test_entry_and_document_line_lot_mismatch_aborts_expand(self):
        self.assertIn(
            "entry snapshot rollback: OK",
            self._run_scenario("entry_mismatch"),
        )


pytestmark = pytest.mark.integration
