from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Department
from apps.warehouse.models import (
    FundingSource,
    StockDocument,
    StockDocumentLine,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
)
from apps.warehouse.reports import (
    build_department_availability,
    build_expense_report,
    build_rack_card,
    export_csv,
    export_xlsx,
)
from apps.warehouse.services import inline_series_reconciliation, post_document


class Command(BaseCommand):
    help = "Сквозная приёмка: приход, адресное перемещение, расход и три отчёта."

    def handle(self, *args, **options):
        with transaction.atomic():
            suffix = "__warehouse_acceptance_e2e__"
            department = Department.objects.create(name=suffix)
            actor = get_user_model().objects.create_superuser(
                username=suffix, department=department
            )
            category = WarehouseItemCategory.objects.create(code=suffix, name="E2E")
            unit = UnitOfMeasure.objects.create(
                code=suffix, name="шт.", quantity_precision=0
            )
            item = WarehouseItem.objects.create(
                code=suffix, name="E2E препарат", category=category, unit=unit
            )
            funding = FundingSource.objects.create(code=suffix, name="E2E источник")
            warehouse = Warehouse.objects.create(
                department=department, code=suffix, name="E2E склад"
            )
            rack_a = StorageLocation.objects.create(
                warehouse=warehouse, code="E2E-A", name="Стеллаж A"
            )
            rack_b = StorageLocation.objects.create(
                warehouse=warehouse, code="E2E-B", name="Стеллаж B"
            )
            series = "E2E-SERIES"
            expires_on = date.today() + timedelta(days=365)

            self._post(actor, department, StockDocument.DocumentType.RECEIPT, 10, item, series, expires_on, funding, destination=rack_a)
            self._post(actor, department, StockDocument.DocumentType.RELOCATION, 3, item, series, expires_on, funding, source=rack_a, destination=rack_b)
            issue = self._post(actor, department, StockDocument.DocumentType.ISSUE, 2, item, series, expires_on, funding, source=rack_b)
            if issue.number:
                raise AssertionError("Номер требования должен оставаться необязательным.")

            department_ids = {department.pk}
            expense = build_expense_report(
                department_ids=department_ids,
                period_start=date.today(),
                period_end=date.today(),
            )
            rack_card = build_rack_card(department_ids=department_ids, as_of=date.today())
            availability = build_department_availability(
                department_ids=department_ids, as_of=date.today()
            )
            if not expense or sum(row["closing"] for row in expense) != 8:
                raise AssertionError("Неверный итог отчёта о расходе.")
            if sum(row["quantity"] for row in rack_card) != 8:
                raise AssertionError("Неверный итог стеллажной карты.")
            if sum(row["quantity"] for row in availability) != 8:
                raise AssertionError("Неверный итог наличия в подразделении.")
            if not export_csv(expense) or not export_xlsx(rack_card):
                raise AssertionError("Экспорт отчёта не сформирован.")
            reconciliation = inline_series_reconciliation(
                actor=actor,
                department_id=department.pk,
            )
            if not reconciliation["ok"] or reconciliation["entry_count"] != 4:
                raise AssertionError("Сверка inline-серий не подтвердила журнал.")
            transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("Warehouse acceptance e2e: OK"))

    @staticmethod
    def _post(
        actor,
        department,
        document_type,
        quantity,
        item,
        series,
        expires_on,
        funding,
        *,
        source=None,
        destination=None,
    ):
        document = StockDocument.objects.create(
            department=department,
            document_type=document_type,
            operation_date=date.today(),
            created_by=actor,
        )
        StockDocumentLine.objects.create(
            document=document,
            item=item,
            series=series,
            expires_on=expires_on,
            funding_source=funding,
            quantity=quantity,
            source_location=source,
            destination_location=destination,
        )
        return post_document(document_id=document.pk, actor=actor)
