from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import Department
from apps.warehouse.models import (
    FundingSource,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockEntry,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
)
from apps.warehouse.services import (
    post_document,
    inline_series_reconciliation,
    rebuild_stock_balances,
    reverse_document,
    stock_balance_mismatches,
)
from apps.warehouse.services import posting as posting_service


class WarehousePostingTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Аптека")
        self.actor = get_user_model().objects.create_superuser(
            username="warehouse-root", department=self.department
        )
        self.category = WarehouseItemCategory.objects.create(code="drug", name="Препараты")
        self.unit = UnitOfMeasure.objects.create(code="pcs", name="шт.", quantity_precision=0)
        self.item = WarehouseItem.objects.create(
            code="item-1",
            name="Тестовый препарат",
            category=self.category,
            unit=self.unit,
        )
        self.funding = FundingSource.objects.create(code="oms", name="ОМС")
        self.warehouse = Warehouse.objects.create(
            department=self.department, code="main", name="Основной"
        )
        self.location = StorageLocation.objects.create(
            warehouse=self.warehouse, code="R-01", name="Стеллаж 1"
        )
        self.other_location = StorageLocation.objects.create(
            warehouse=self.warehouse, code="R-02", name="Стеллаж 2"
        )
        self.series = "A-1"
        self.expires_on = date.today() + timedelta(days=365)

    def _document(
        self,
        document_type,
        quantity,
        *,
        series=None,
        expires_on=None,
        source=None,
        destination=None,
        reason="",
        incomplete_reason="",
    ):
        document = StockDocument.objects.create(
            department=self.department,
            document_type=document_type,
            operation_date=date.today(),
            reason=reason,
            created_by=self.actor,
        )
        StockDocumentLine.objects.create(
            document=document,
            item=self.item,
            series=series if series is not None else self.series,
            expires_on=expires_on if expires_on is not None else self.expires_on,
            incomplete_reason=incomplete_reason,
            funding_source=self.funding,
            quantity=quantity,
            source_location=source,
            destination_location=destination,
        )
        return document

    def _receive(self, quantity=10, *, series=None, expires_on=None, destination=None):
        document = self._document(
            StockDocument.DocumentType.RECEIPT,
            quantity,
            series=series,
            expires_on=expires_on,
            destination=destination or self.location,
        )
        return post_document(document_id=document.pk, actor=self.actor)

    def test_receipt_and_issue_update_immutable_ledger_and_balance(self):
        receipt = self._receive(10)
        issue = self._document(
            StockDocument.DocumentType.ISSUE,
            4,
            source=self.location,
        )
        post_document(document_id=issue.pk, actor=self.actor)

        self.assertEqual(receipt.status, StockDocument.Status.POSTED)
        self.assertEqual(list(StockEntry.objects.values_list("quantity", flat=True)), [
            Decimal("10.000000"), Decimal("-4.000000")
        ])
        self.assertEqual(StockBalance.objects.get().quantity, Decimal("6.000000"))
        self.assertEqual(issue.number, "")
        with self.assertRaises(ValidationError):
            receipt.comment = "изменение после проведения"
            receipt.save()

    def test_fractional_quantity_is_rejected_by_unit_precision(self):
        document = self._document(
            StockDocument.DocumentType.RECEIPT,
            Decimal("1.5"),
            destination=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=document.pk, actor=self.actor)
        self.assertFalse(StockEntry.objects.exists())
        self.assertFalse(StockBalance.objects.exists())

    def test_negative_balance_rolls_back_document_and_projection(self):
        document = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=document.pk, actor=self.actor)
        document.refresh_from_db()
        self.assertEqual(document.status, StockDocument.Status.DRAFT)
        self.assertFalse(StockEntry.objects.exists())
        self.assertFalse(StockBalance.objects.exists())

    def test_issue_rejects_expired_and_unavailable_locations(self):
        expired_on = date.today() - timedelta(days=1)
        self._receive(2, series="OLD", expires_on=expired_on)
        expired_issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            series="OLD",
            expires_on=expired_on,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=expired_issue.pk, actor=self.actor)

        self.location.purpose = StorageLocation.Purpose.QUARANTINE
        self.location.save(update_fields=["purpose"])
        unavailable_issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            series="OLD",
            expires_on=expired_on,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=unavailable_issue.pk, actor=self.actor)

    def test_ordinary_operations_reject_quarantine_and_inactive_locations(self):
        quarantine = StorageLocation.objects.create(
            warehouse=self.warehouse,
            code="Q-01",
            name="Карантин",
            purpose=StorageLocation.Purpose.QUARANTINE,
        )
        receipt = self._document(
            StockDocument.DocumentType.RECEIPT,
            1,
            destination=quarantine,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=receipt.pk, actor=self.actor)

        unassigned = StorageLocation.objects.create(
            warehouse=self.warehouse,
            code="U-01",
            name="Адрес не назначен",
            purpose=StorageLocation.Purpose.UNASSIGNED,
        )
        opening = self._document(
            StockDocument.DocumentType.OPENING,
            1,
            destination=unassigned,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=opening.pk, actor=self.actor)

        self._receive(2)
        self.location.is_active = False
        self.location.save(update_fields=["is_active"])
        issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=issue.pk, actor=self.actor)

    def test_fefo_override_requires_explicit_line_reason(self):
        earlier_expiry = date.today() + timedelta(days=30)
        self._receive(3, series="EARLY", expires_on=earlier_expiry)
        self._receive(3, series=self.series, expires_on=self.expires_on)
        issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            series=self.series,
            expires_on=self.expires_on,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=issue.pk, actor=self.actor)
        line = issue.lines.get()
        line.fefo_override_reason = "Серия зарезервирована по назначению"
        line.save(update_fields=["fefo_override_reason"])
        post_document(document_id=issue.pk, actor=self.actor)
        self.assertEqual(
            StockBalance.objects.get(series_key="a-1").quantity,
            Decimal("2"),
        )

    def test_relocation_is_balanced_and_reversal_restores_source_document(self):
        self._receive(5)
        relocation = self._document(
            StockDocument.DocumentType.RELOCATION,
            2,
            source=self.location,
            destination=self.other_location,
        )
        post_document(document_id=relocation.pk, actor=self.actor)
        self.assertEqual(
            StockBalance.objects.get(location=self.location).quantity, Decimal("3")
        )
        self.assertEqual(
            StockBalance.objects.get(location=self.other_location).quantity, Decimal("2")
        )

        reversal = reverse_document(
            source_document_id=relocation.pk,
            actor=self.actor,
            operation_date=date.today(),
            reason="Ошибочный адрес",
        )
        self.assertEqual(reversal.status, StockDocument.Status.POSTED)
        self.assertEqual(
            StockBalance.objects.get(location=self.location).quantity, Decimal("5")
        )
        self.assertEqual(
            StockBalance.objects.get(location=self.other_location).quantity, Decimal("0")
        )

    def test_projection_can_be_rebuilt_from_entries(self):
        self._receive(7)
        self.assertEqual(
            stock_balance_mismatches(actor=self.actor, department_id=self.department.pk),
            [],
        )
        StockBalance.objects.all().delete()
        self.assertEqual(
            len(
                stock_balance_mismatches(
                    actor=self.actor, department_id=self.department.pk
                )
            ),
            1,
        )
        count = rebuild_stock_balances(actor=self.actor, department_id=self.department.pk)
        self.assertEqual(count, 1)
        self.assertEqual(StockBalance.objects.get().quantity, Decimal("7"))

    def test_manually_forged_reversal_is_rejected(self):
        receipt = self._receive(5)
        reversal = StockDocument.objects.create(
            department=self.department,
            document_type=StockDocument.DocumentType.REVERSAL,
            operation_date=date.today(),
            reason="Проверка некорректного сторно",
            created_by=self.actor,
            reverses_document=receipt,
        )
        original_line = receipt.lines.get()
        StockDocumentLine.objects.create(
            document=reversal,
            sequence=original_line.sequence,
            item=original_line.item,
            series=original_line.series,
            expires_on=original_line.expires_on,
            incomplete_reason=original_line.incomplete_reason,
            funding_source=original_line.funding_source,
            quantity=4,
            destination_location=original_line.destination_location,
        )

        with self.assertRaises(ValidationError):
            post_document(document_id=reversal.pk, actor=self.actor)

        reversal.refresh_from_db()
        self.assertEqual(reversal.status, StockDocument.Status.DRAFT)
        self.assertEqual(StockBalance.objects.get().quantity, Decimal("5"))

    def test_series_is_normalized_and_conflicting_expiry_is_rejected(self):
        self._receive(2, series="  AbC   1  ", expires_on=self.expires_on)
        entry = StockEntry.objects.get()
        self.assertEqual(entry.series, "AbC 1")
        self.assertEqual(entry.series_key, "abc 1")

        conflict = self._document(
            StockDocument.DocumentType.RECEIPT,
            1,
            series="ABC 1",
            expires_on=self.expires_on + timedelta(days=1),
            destination=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=conflict.pk, actor=self.actor)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, StockDocument.Status.DRAFT)

    def test_series_conflict_is_rechecked_after_deterministic_item_lock(self):
        candidate = self._document(
            StockDocument.DocumentType.RECEIPT,
            1,
            series="RACE-1",
            expires_on=self.expires_on,
            destination=self.location,
        )
        concurrent_document = self._document(
            StockDocument.DocumentType.RECEIPT,
            1,
            series="race-1",
            expires_on=self.expires_on + timedelta(days=1),
            destination=self.location,
        )
        concurrent_line = concurrent_document.lines.get()
        StockDocument.objects.filter(pk=concurrent_document.pk).update(
            status=StockDocument.Status.POSTED
        )

        original_lock = posting_service._lock_document_items
        observed = []

        def insert_after_lock(document):
            locked_ids = original_lock(document)
            observed.append(locked_ids)
            StockEntry.objects.create(
                document=concurrent_document,
                document_line=concurrent_line,
                department=self.department,
                warehouse=self.warehouse,
                location=self.location,
                item=self.item,
                series=concurrent_line.series,
                expires_on=concurrent_line.expires_on,
                unit=self.unit,
                funding_source=self.funding,
                quantity=1,
                operation_date=date.today(),
            )
            return locked_ids

        with patch.object(
            posting_service,
            "_lock_document_items",
            side_effect=insert_after_lock,
        ):
            with self.assertRaises(ValidationError) as caught:
                post_document(document_id=candidate.pk, actor=self.actor)

        self.assertEqual(observed, [(self.item.pk,)])
        self.assertIn("expires_on", caught.exception.message_dict)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status, StockDocument.Status.DRAFT)

    def test_inline_series_reconciliation_exposes_stable_checksums(self):
        self._receive(7)
        first = inline_series_reconciliation(
            actor=self.actor, department_id=self.department.pk
        )
        second = inline_series_reconciliation(
            actor=self.actor, department_id=self.department.pk
        )
        self.assertTrue(first["ok"])
        self.assertEqual(first["journal_checksum"], second["journal_checksum"])
        self.assertEqual(
            first["expected_projection_checksum"],
            first["actual_projection_checksum"],
        )
pytestmark = pytest.mark.integration
