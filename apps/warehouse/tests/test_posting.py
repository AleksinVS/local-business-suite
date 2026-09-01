from datetime import date, timedelta
from decimal import Decimal

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
    StockLot,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
)
from apps.warehouse.services import (
    post_document,
    rebuild_stock_balances,
    reverse_document,
    stock_balance_mismatches,
)


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
        self.lot = StockLot.objects.create(
            item=self.item,
            batch_number="A-1",
            expires_on=date.today() + timedelta(days=365),
        )

    def _document(self, document_type, quantity, *, lot=None, source=None, destination=None, reason=""):
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
            lot=lot or self.lot,
            funding_source=self.funding,
            quantity=quantity,
            source_location=source,
            destination_location=destination,
        )
        return document

    def _receive(self, quantity=10, *, lot=None, destination=None):
        document = self._document(
            StockDocument.DocumentType.RECEIPT,
            quantity,
            lot=lot,
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
        expired_lot = StockLot.objects.create(
            item=self.item,
            batch_number="OLD",
            expires_on=date.today() - timedelta(days=1),
        )
        self._receive(2, lot=expired_lot)
        expired_issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            lot=expired_lot,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=expired_issue.pk, actor=self.actor)

        self.location.purpose = StorageLocation.Purpose.QUARANTINE
        self.location.save(update_fields=["purpose"])
        unavailable_issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            lot=expired_lot,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=unavailable_issue.pk, actor=self.actor)

    def test_fefo_override_requires_explicit_line_reason(self):
        earlier = StockLot.objects.create(
            item=self.item,
            batch_number="EARLY",
            expires_on=date.today() + timedelta(days=30),
        )
        self._receive(3, lot=earlier)
        self._receive(3, lot=self.lot)
        issue = self._document(
            StockDocument.DocumentType.ISSUE,
            1,
            lot=self.lot,
            source=self.location,
        )
        with self.assertRaises(ValidationError):
            post_document(document_id=issue.pk, actor=self.actor)
        line = issue.lines.get()
        line.fefo_override_reason = "Серия зарезервирована по назначению"
        line.save(update_fields=["fefo_override_reason"])
        post_document(document_id=issue.pk, actor=self.actor)
        self.assertEqual(StockBalance.objects.get(lot=self.lot).quantity, Decimal("2"))

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
            lot=original_line.lot,
            funding_source=original_line.funding_source,
            quantity=4,
            destination_location=original_line.destination_location,
        )

        with self.assertRaises(ValidationError):
            post_document(document_id=reversal.pk, actor=self.actor)

        reversal.refresh_from_db()
        self.assertEqual(reversal.status, StockDocument.Status.DRAFT)
        self.assertEqual(StockBalance.objects.get().quantity, Decimal("5"))
pytestmark = pytest.mark.integration
