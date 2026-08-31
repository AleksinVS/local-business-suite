from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from io import BytesIO
from zipfile import ZipFile

from apps.warehouse.models import StockDocument
from apps.warehouse.reports.datasets import build_expense_report
from apps.warehouse.reports.exports import export_csv, export_xlsx


def _entry(quantity, operation_date, department_id=1, item_id=2, funding_id=3, unit_id=4, kind="receipt"):
    item = SimpleNamespace(name="Item", id=item_id)
    lot = SimpleNamespace(item=item, item_id=item_id)
    document = SimpleNamespace(status=StockDocument.Status.POSTED, document_type=kind, reverses_document_id=None)
    return SimpleNamespace(quantity=Decimal(quantity), operation_date=operation_date, department_id=department_id,
                           funding_source_id=funding_id, unit_id=unit_id, lot=lot, document=document,
                           department=SimpleNamespace(name="Dept"), funding_source=SimpleNamespace(name="Fund"),
                           unit=SimpleNamespace(name="pcs"))


class WarehouseReportDatasetTests(TestCase):
    def test_expense_arithmetic_and_scope(self):
        rows = build_expense_report(
            department_ids=[1], period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            entries=[_entry("10", date(2025, 12, 1)), _entry("3", date(2026, 1, 2), kind="issue"), _entry("99", date(2026, 1, 2), department_id=2)],
        )
        self.assertEqual(rows[0]["opening"], Decimal("10"))
        self.assertEqual(rows[0]["outgoing"], Decimal("3"))
        self.assertEqual(rows[0]["closing"], Decimal("7"))


class WarehouseReportExportTests(TestCase):
    def test_csv_is_bom_and_formula_safe(self):
        result = export_csv([{"name": "=SUM(A1)", "quantity": Decimal("2")}])
        text = result.decode("utf-8-sig")
        self.assertTrue(result.startswith(b"\xef\xbb\xbf"))
        self.assertIn("'=SUM(A1)", text)

    def test_xlsx_writes_user_values_as_safe_strings_and_includes_metadata(self):
        result = export_xlsx(
            [{"name": "=SUM(A1)", "quantity": Decimal("2")}],
            metadata={"Подписант": "@example"},
        )
        with ZipFile(BytesIO(result)) as archive:
            shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
            worksheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("'=SUM(A1)", shared_strings)
        self.assertIn("'@example", shared_strings)
        self.assertNotIn("<f>", worksheet)
