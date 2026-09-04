from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
import importlib
from pathlib import Path
import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import path, resolve, reverse

from apps.core.contract_store import _reset_for_tests
from apps.core.models import Department
from apps.warehouse.models import (
    FundingSource,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
)
from apps.warehouse.relocation import (
    RelocationLineRequest,
    WarehouseRelocationError,
    create_and_post_relocation,
)
from apps.warehouse.relocation_forms import (
    RelocationSelection,
    dump_relocation_selection,
    load_relocation_selection,
)
from apps.warehouse.relocation_selectors import (
    filtered_relocatable_stock_balances_queryset,
    paginated_relocatable_stock_balances,
    sanitized_stock_filter_query,
)
from apps.warehouse.relocation_views import (
    RelocationDestinationAutocompleteView,
    RelocationLocationAutocompleteView,
    relocation_create_view,
    relocation_panel_view,
    relocation_stock_list_view,
)
from apps.warehouse.services import post_document, reverse_document


urlpatterns = [
    path("warehouse/stock/", relocation_stock_list_view, name="relocation-stock"),
    path("warehouse/relocations/panel/", relocation_panel_view, name="relocation-panel"),
    path("warehouse/relocations/", relocation_create_view, name="relocation-create"),
    path(
        "warehouse/relocations/autocomplete/destinations/",
        RelocationDestinationAutocompleteView.as_view(),
        name="relocation-destinations",
    ),
    path(
        "warehouse/relocations/autocomplete/locations/",
        RelocationLocationAutocompleteView.as_view(),
        name="relocation-locations",
    ),
]


ROLE_RULES = Path(settings.BASE_DIR) / "contracts" / "role_rules.json"


@override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=ROLE_RULES)
class RelocationModeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Department.objects.create(name="MOVE-ORG")
        cls.own = Department.objects.create(name="MOVE-OWN", parent=cls.organization)
        cls.child = Department.objects.create(name="MOVE-CHILD", parent=cls.own)
        cls.foreign = Department.objects.create(name="MOVE-FOREIGN")
        operator_group, _ = Group.objects.get_or_create(name="warehouse_operator")
        cls.operator = get_user_model().objects.create_user(
            username="move-operator", department=cls.own
        )
        cls.operator.groups.add(operator_group)
        cls.superuser = get_user_model().objects.create_superuser(
            username="move-root", department=cls.own
        )
        cls.unit = UnitOfMeasure.objects.create(
            code="move-pcs", name="шт.", quantity_precision=0
        )
        cls.category = WarehouseItemCategory.objects.create(
            code="move-drug", name="Препараты"
        )
        cls.item_a = WarehouseItem.objects.create(
            code="move-a", name="Препарат A", unit=cls.unit, category=cls.category
        )
        cls.item_b = WarehouseItem.objects.create(
            code="move-b", name="Препарат B", unit=cls.unit, category=cls.category
        )
        cls.funding = FundingSource.objects.create(code="move-oms", name="ОМС")
        cls.source_warehouse = Warehouse.objects.create(
            department=cls.own, code="move-source", name="Исходный"
        )
        cls.source_location = StorageLocation.objects.create(
            warehouse=cls.source_warehouse, code="SRC", name="Исходный стеллаж"
        )
        cls.destination_warehouse = Warehouse.objects.create(
            department=cls.own, code="move-dest", name="Получатель"
        )
        cls.destination_location = StorageLocation.objects.create(
            warehouse=cls.destination_warehouse, code="DST", name="Приёмка"
        )
        cls.quarantine_location = StorageLocation.objects.create(
            warehouse=cls.destination_warehouse,
            code="QUA",
            name="Карантин",
            purpose=StorageLocation.Purpose.QUARANTINE,
        )
        Warehouse.objects.filter(pk=cls.destination_warehouse.pk).update(
            default_receiving_location=cls.destination_location
        )
        cls.destination_warehouse.refresh_from_db()
        cls.child_warehouse = Warehouse.objects.create(
            department=cls.child, code="move-child", name="Дочерний склад"
        )
        cls.child_location = StorageLocation.objects.create(
            warehouse=cls.child_warehouse, code="CHILD", name="Дочерний адрес"
        )
        cls.foreign_warehouse = Warehouse.objects.create(
            department=cls.foreign, code="move-foreign", name="Чужой склад"
        )
        cls.foreign_location = StorageLocation.objects.create(
            warehouse=cls.foreign_warehouse, code="FOREIGN", name="Чужой адрес"
        )

    def setUp(self):
        _reset_for_tests()
        self.balance_a = self._receive(self.own, self.source_location, self.item_a, 10, "A-1")
        self.balance_b = self._receive(self.own, self.source_location, self.item_b, 7, "B-1")

    def tearDown(self):
        _reset_for_tests()

    def _receive(self, department, location, item, quantity, series):
        document = StockDocument.objects.create(
            department=department,
            document_type=StockDocument.DocumentType.RECEIPT,
            operation_date=date.today(),
            created_by=self.superuser,
        )
        StockDocumentLine.objects.create(
            document=document,
            item=item,
            series=series,
            expires_on=date.today() + timedelta(days=365),
            funding_source=self.funding,
            quantity=quantity,
            destination_location=location,
        )
        post_document(document_id=document.pk, actor=self.superuser)
        return StockBalance.objects.get(location=location, item=item, series_key=series.casefold())

    def _line(self, balance, quantity):
        return RelocationLineRequest(
            balance_id=balance.pk,
            quantity=Decimal(quantity),
            expected_quantity=balance.quantity,
        )

    def test_moves_multiple_rows_as_one_posted_reversible_document(self):
        document = create_and_post_relocation(
            actor=self.operator,
            lines=[self._line(self.balance_a, "3"), self._line(self.balance_b, "2")],
            destination_warehouse_id=self.destination_warehouse.pk,
        )

        self.assertEqual(document.status, StockDocument.Status.POSTED)
        self.assertEqual(document.document_type, StockDocument.DocumentType.RELOCATION)
        self.assertEqual(document.lines.count(), 2)
        self.assertEqual(document.entries.count(), 4)
        self.assertEqual(
            StockBalance.objects.get(pk=self.balance_a.pk).quantity, Decimal("7")
        )
        self.assertEqual(
            StockBalance.objects.get(
                location=self.destination_location, item=self.item_a
            ).quantity,
            Decimal("3"),
        )

        reversal = reverse_document(
            source_document_id=document.pk,
            actor=self.superuser,
            operation_date=date.today(),
            reason="Возврат перемещения",
        )
        self.assertEqual(reversal.status, StockDocument.Status.POSTED)
        self.assertEqual(
            StockBalance.objects.get(pk=self.balance_a.pk).quantity, Decimal("10")
        )

    def test_stale_snapshot_rolls_back_every_selected_line(self):
        StockBalance.objects.filter(pk=self.balance_a.pk).update(quantity=9)
        before_b = StockBalance.objects.get(pk=self.balance_b.pk).quantity

        with self.assertRaisesMessage(ValidationError, "изменился"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[self._line(self.balance_a, "3"), self._line(self.balance_b, "2")],
                destination_warehouse_id=self.destination_warehouse.pk,
            )

        self.assertFalse(
            StockDocument.objects.filter(
                document_type=StockDocument.DocumentType.RELOCATION
            ).exists()
        )
        self.assertEqual(StockBalance.objects.get(pk=self.balance_b.pk).quantity, before_b)
        self.assertFalse(
            StockBalance.objects.filter(location=self.destination_location).exists()
        )

    def test_repeated_idempotency_key_returns_the_same_document(self):
        command_key = uuid.uuid4()
        line = self._line(self.balance_a, "2")
        first = create_and_post_relocation(
            actor=self.operator,
            lines=[line],
            destination_warehouse_id=self.destination_warehouse.pk,
            idempotency_key=command_key,
        )
        second = create_and_post_relocation(
            actor=self.operator,
            lines=[line],
            destination_warehouse_id=self.destination_warehouse.pk,
            idempotency_key=command_key,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            StockBalance.objects.get(pk=self.balance_a.pk).quantity, Decimal("8")
        )

    def test_reused_idempotency_key_rejects_changed_command_semantics(self):
        command_key = uuid.uuid4()
        original = self._line(self.balance_a, "2")
        create_and_post_relocation(
            actor=self.operator,
            lines=[original],
            destination_warehouse_id=self.destination_warehouse.pk,
            idempotency_key=command_key,
        )
        with self.assertRaisesMessage(ValidationError, "не относится"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[original],
                destination_warehouse_id=self.source_warehouse.pk,
                destination_location_id=self.destination_location.pk,
                operation_date=date.today(),
                idempotency_key=command_key,
            )
        altered = RelocationLineRequest(
            balance_id=self.balance_a.pk,
            quantity=Decimal("1"),
            expected_quantity=Decimal("10"),
        )
        with self.assertRaisesMessage(ValidationError, "другого перемещения"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[altered],
                destination_warehouse_id=self.destination_warehouse.pk,
                idempotency_key=command_key,
            )
        with self.assertRaisesMessage(ValidationError, "другого перемещения"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[original],
                destination_warehouse_id=self.source_warehouse.pk,
                destination_location_id=self.source_location.pk,
                idempotency_key=command_key,
            )
        with self.assertRaisesMessage(ValidationError, "другого перемещения"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[original],
                destination_warehouse_id=self.destination_warehouse.pk,
                operation_date=date.today() + timedelta(days=1),
                idempotency_key=command_key,
            )
        with self.assertRaisesMessage(ValidationError, "другого перемещения"):
            create_and_post_relocation(
                actor=self.superuser,
                lines=[original],
                destination_warehouse_id=self.destination_warehouse.pk,
                idempotency_key=command_key,
            )

    def test_hostile_decimal_exponent_is_rejected_without_expansion(self):
        hostile = RelocationLineRequest(
            balance_id=self.balance_a.pk,
            quantity=Decimal("1e-100000000"),
            expected_quantity=self.balance_a.quantity,
        )
        with self.assertRaisesMessage(ValidationError, "допустимые пределы"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[hostile],
                destination_warehouse_id=self.destination_warehouse.pk,
            )
        with self.assertRaisesMessage(ValidationError, "допустимые пределы"):
            dump_relocation_selection(
                RelocationSelection(
                    department_id=self.own.pk,
                    idempotency_key=uuid.uuid4(),
                    lines=(hostile,),
                    balances=(self.balance_a,),
                )
            )

    def test_forged_foreign_balance_and_destination_are_rejected(self):
        foreign_balance = self._receive(
            self.foreign, self.foreign_location, self.item_a, 5, "FOREIGN"
        )
        with self.assertRaises(PermissionDenied):
            create_and_post_relocation(
                actor=self.operator,
                lines=[self._line(foreign_balance, "1")],
                destination_warehouse_id=self.destination_warehouse.pk,
            )
        with self.assertRaises(PermissionDenied):
            create_and_post_relocation(
                actor=self.operator,
                lines=[self._line(self.balance_a, "1")],
                destination_warehouse_id=self.foreign_warehouse.pk,
                destination_location_id=self.foreign_location.pk,
            )

    def test_quarantine_and_same_source_destination_are_rejected(self):
        with self.assertRaisesMessage(ValidationError, "недоступен"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[self._line(self.balance_a, "1")],
                destination_warehouse_id=self.destination_warehouse.pk,
                destination_location_id=self.quarantine_location.pk,
            )
        with self.assertRaisesMessage(ValidationError, "различаться"):
            create_and_post_relocation(
                actor=self.operator,
                lines=[self._line(self.balance_a, "1")],
                destination_warehouse_id=self.source_warehouse.pk,
                destination_location_id=self.source_location.pk,
            )

    def test_inactive_source_is_rejected_for_issue_by_canonical_posting_service(self):
        self.source_location.is_active = False
        self.source_location.save(update_fields=["is_active"])
        document = StockDocument.objects.create(
            department=self.own,
            document_type=StockDocument.DocumentType.ISSUE,
            operation_date=date.today(),
            created_by=self.superuser,
        )
        StockDocumentLine.objects.create(
            document=document,
            item=self.item_a,
            series="A-1",
            expires_on=date.today() + timedelta(days=365),
            funding_source=self.funding,
            quantity=1,
            source_location=self.source_location,
        )
        with self.assertRaisesMessage(ValidationError, "активном адресе"):
            post_document(document_id=document.pk, actor=self.superuser)

    def test_warehouse_default_location_validation(self):
        self.destination_warehouse.default_receiving_location = self.foreign_location
        with self.assertRaises(ValidationError):
            self.destination_warehouse.full_clean()
        self.destination_warehouse.default_receiving_location = self.quarantine_location
        with self.assertRaises(ValidationError):
            self.destination_warehouse.full_clean()

        self.quarantine_location.purpose = StorageLocation.Purpose.AVAILABLE
        self.quarantine_location.save()
        self.destination_warehouse.default_receiving_location = self.quarantine_location
        self.destination_warehouse.full_clean()

    def test_signed_selection_detects_tampering(self):
        selection = RelocationSelection(
            department_id=self.own.pk,
            idempotency_key=uuid.uuid4(),
            lines=(self._line(self.balance_a, "2"),),
            balances=(self.balance_a,),
        )
        token = dump_relocation_selection(selection)
        department_id, lines, command_key = load_relocation_selection(token)
        self.assertEqual(department_id, self.own.pk)
        self.assertEqual(lines[0].quantity, Decimal("2"))
        self.assertEqual(command_key, selection.idempotency_key)
        with self.assertRaises(ValidationError):
            load_relocation_selection(token + "tampered")

    def test_filters_are_scoped_and_paginated_without_silent_cap(self):
        foreign_balance = self._receive(
            self.foreign, self.foreign_location, self.item_a, 5, "NO-VIEW"
        )
        queryset = filtered_relocatable_stock_balances_queryset(
            self.operator, {"item": "Препарат", "series": "-1"}
        )
        self.assertIn(self.balance_a, queryset)
        self.assertNotIn(foreign_balance, queryset)
        page = paginated_relocatable_stock_balances(
            self.operator, {}, page_size=1
        )
        self.assertEqual(page.paginator.count, 2)
        self.assertEqual(page.paginator.num_pages, 2)
        query = sanitized_stock_filter_query(
            {
                "department_id": str(self.own.pk),
                "warehouse_id": str(self.source_warehouse.pk),
                "location_id": str(self.source_location.pk),
                "category_id": str(self.category.pk),
                "funding_source_id": str(self.funding.pk),
                "item": "Препарат A",
                "series": "A-1",
                "expires_from": date.today().isoformat(),
                "expires_to": (date.today() + timedelta(days=5)).isoformat(),
                "page": "999",
                "unsafe": "ignored",
            }
        )
        for key in (
            "department_id",
            "warehouse_id",
            "location_id",
            "category_id",
            "funding_source_id",
            "item",
            "series",
            "expires_from",
            "expires_to",
        ):
            self.assertIn(f"{key}=", query)
        self.assertNotIn("page=", query)
        self.assertNotIn("unsafe=", query)

    def test_real_warehouse_url_is_resolvable_and_reachable(self):
        self._receive(
            self.foreign, self.foreign_location, self.item_a, 3, "HIDDEN-FILTER"
        )
        url = reverse("warehouse:stock")
        self.assertIs(resolve(url).func, relocation_stock_list_view)
        client = Client()
        client.force_login(self.operator)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        for field_name in (
            "department_id",
            "warehouse_id",
            "location_id",
            "category_id",
            "funding_source_id",
            "item",
            "series",
            "expires_from",
            "expires_to",
        ):
            self.assertContains(response, f'name="{field_name}"')
        self.assertNotContains(response, self.foreign_warehouse.name)

    @override_settings(ROOT_URLCONF=__name__)
    def test_panel_and_create_views_complete_without_confirmation_step(self):
        client = Client()
        client.force_login(self.operator)
        panel = client.post(
            "/warehouse/relocations/panel/",
            {
                "selected_balance": [self.balance_a.pk, self.balance_b.pk],
                f"quantity_{self.balance_a.pk}": "2",
                f"expected_quantity_{self.balance_a.pk}": str(self.balance_a.quantity),
                f"quantity_{self.balance_b.pk}": "1",
                f"expected_quantity_{self.balance_b.pk}": str(self.balance_b.quantity),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "Сохранить перемещение")
        self.assertContains(panel, "Препарат A")
        token = panel.context["form"].initial["selection_token"]
        _, _, _ = load_relocation_selection(token)

        saved = client.post(
            "/warehouse/relocations/",
            {
                "selection_token": token,
                "operation_date": date.today().isoformat(),
                "destination_warehouse": self.destination_warehouse.pk,
                "destination_location": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(saved.status_code, 200)
        triggers = saved.headers["HX-Trigger"]
        self.assertIn("warehouseStockChanged", triggers)
        self.assertIn("rightPanelFormSucceeded", triggers)
        self.assertEqual(
            StockDocument.objects.filter(
                document_type=StockDocument.DocumentType.RELOCATION,
                status=StockDocument.Status.POSTED,
            ).count(),
            1,
        )
        mismatched_replay = client.post(
            "/warehouse/relocations/",
            {
                "selection_token": token,
                "operation_date": date.today().isoformat(),
                "destination_warehouse": self.source_warehouse.pk,
                "destination_location": self.destination_location.pk,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(mismatched_replay.status_code, 422)
        self.assertEqual(
            StockDocument.objects.filter(
                document_type=StockDocument.DocumentType.RELOCATION
            ).count(),
            1,
        )

    @override_settings(ROOT_URLCONF=__name__)
    def test_destination_autocomplete_is_department_scoped(self):
        client = Client()
        client.force_login(self.operator)
        response = client.get(
            "/warehouse/relocations/autocomplete/destinations/",
            {"department": self.own.pk, "q": "Получ"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([row["value"] for row in payload["results"]], [str(self.destination_warehouse.pk)])


@pytest.mark.skipif(connection.vendor != "postgresql", reason="requires row-level locks")
@override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=ROLE_RULES)
class RelocationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        _reset_for_tests()
        department = Department.objects.create(name="MOVE-RACE")
        group, _ = Group.objects.get_or_create(name="warehouse_operator")
        self.actor = get_user_model().objects.create_user(
            username="move-race-operator", department=department
        )
        self.actor.groups.add(group)
        unit = UnitOfMeasure.objects.create(code="move-race-pcs", name="шт.")
        category = WarehouseItemCategory.objects.create(code="move-race-cat", name="Категория")
        item = WarehouseItem.objects.create(
            code="move-race-item", name="Позиция", unit=unit, category=category
        )
        item_two = WarehouseItem.objects.create(
            code="move-race-item-2", name="Позиция 2", unit=unit, category=category
        )
        funding = FundingSource.objects.create(code="move-race-fund", name="Источник")
        source_warehouse = Warehouse.objects.create(
            department=department, code="move-race-source", name="Источник"
        )
        source = StorageLocation.objects.create(
            warehouse=source_warehouse, code="SRC", name="Источник"
        )
        self.destinations = []
        for suffix in ("A", "B"):
            warehouse = Warehouse.objects.create(
                department=department, code=f"move-race-{suffix}", name=f"Назначение {suffix}"
            )
            location = StorageLocation.objects.create(
                warehouse=warehouse, code="DST", name="Приёмка"
            )
            Warehouse.objects.filter(pk=warehouse.pk).update(
                default_receiving_location=location
            )
            self.destinations.append(warehouse.pk)
        root = get_user_model().objects.create_superuser(
            username="move-race-root", department=department
        )
        receipt = StockDocument.objects.create(
            department=department,
            document_type=StockDocument.DocumentType.RECEIPT,
            operation_date=date.today(),
            created_by=root,
        )
        StockDocumentLine.objects.create(
            document=receipt,
            item=item,
            series="RACE",
            expires_on=date.today() + timedelta(days=10),
            funding_source=funding,
            quantity=5,
            destination_location=source,
        )
        post_document(document_id=receipt.pk, actor=root)
        self.balance = StockBalance.objects.get(location=source)
        receipt_two = StockDocument.objects.create(
            department=department,
            document_type=StockDocument.DocumentType.RECEIPT,
            operation_date=date.today(),
            created_by=root,
        )
        StockDocumentLine.objects.create(
            document=receipt_two,
            item=item_two,
            series="RACE-2",
            expires_on=date.today() + timedelta(days=10),
            funding_source=funding,
            quantity=5,
            destination_location=source,
        )
        post_document(document_id=receipt_two.pk, actor=root)
        self.balance_two = StockBalance.objects.get(location=source, item=item_two)
        self.source = source
        self.department = department
        self.funding = funding

    def tearDown(self):
        _reset_for_tests()

    def test_competing_relocations_cannot_partially_overspend(self):
        def move(destination_id):
            close_old_connections()
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                document = create_and_post_relocation(
                    actor=actor,
                    lines=[
                        RelocationLineRequest(
                            self.balance.pk, Decimal("4"), Decimal("5")
                        )
                    ],
                    destination_warehouse_id=destination_id,
                )
                return ("ok", document.pk)
            except ValidationError as exc:
                return ("rejected", str(exc))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(move, self.destinations))
        self.assertEqual([status for status, _ in results].count("ok"), 1)
        self.assertEqual([status for status, _ in results].count("rejected"), 1)
        self.assertEqual(
            StockDocument.objects.filter(
                document_type=StockDocument.DocumentType.RELOCATION,
                status=StockDocument.Status.POSTED,
            ).count(),
            1,
        )

    def test_opposite_multi_item_request_order_has_no_deadlock(self):
        def move(destination_id, balances):
            close_old_connections()
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                document = create_and_post_relocation(
                    actor=actor,
                    lines=[
                        RelocationLineRequest(row.pk, Decimal("1"), Decimal("5"))
                        for row in balances
                    ],
                    destination_warehouse_id=destination_id,
                )
                return ("ok", document.pk)
            except ValidationError as exc:
                return ("rejected", str(exc))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    move,
                    self.destinations[0],
                    [self.balance, self.balance_two],
                ),
                pool.submit(
                    move,
                    self.destinations[1],
                    [self.balance_two, self.balance],
                ),
            ]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual([status for status, _ in results].count("ok"), 1)
        self.assertEqual([status for status, _ in results].count("rejected"), 1)

    def test_quick_relocation_serializes_with_regular_posting(self):
        issue = StockDocument.objects.create(
            department=self.department,
            document_type=StockDocument.DocumentType.ISSUE,
            operation_date=date.today(),
            created_by=self.actor,
        )
        source_balance = StockBalance.objects.get(pk=self.balance.pk)
        StockDocumentLine.objects.create(
            document=issue,
            item=source_balance.item,
            series=source_balance.series,
            expires_on=source_balance.expires_on,
            funding_source=self.funding,
            quantity=4,
            source_location=self.source,
        )

        def relocate():
            close_old_connections()
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                create_and_post_relocation(
                    actor=actor,
                    lines=[
                        RelocationLineRequest(
                            self.balance.pk, Decimal("4"), Decimal("5")
                        )
                    ],
                    destination_warehouse_id=self.destinations[0],
                )
                return "relocation"
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        def issue_stock():
            close_old_connections()
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                post_document(document_id=issue.pk, actor=actor)
                return "issue"
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(relocate), pool.submit(issue_stock)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(len(set(results) - {"rejected"}), 1)
        self.assertGreaterEqual(StockBalance.objects.get(pk=self.balance.pk).quantity, 0)

    def test_duplicate_idempotency_race_returns_one_document(self):
        command_key = uuid.uuid4()

        def move():
            close_old_connections()
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                document = create_and_post_relocation(
                    actor=actor,
                    lines=[
                        RelocationLineRequest(
                            self.balance.pk, Decimal("4"), Decimal("5")
                        )
                    ],
                    destination_warehouse_id=self.destinations[0],
                    idempotency_key=command_key,
                )
                return document.pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(move), pool.submit(move)]
            document_ids = [future.result(timeout=20) for future in futures]
        self.assertEqual(len(set(document_ids)), 1)
        self.assertEqual(
            StockDocument.objects.filter(idempotency_key=command_key).count(), 1
        )
        self.assertEqual(
            StockBalance.objects.get(pk=self.balance.pk).quantity, Decimal("1")
        )


class DefaultReceivingLocationMigrationTests(TestCase):
    def test_forward_populates_only_unambiguous_available_location(self):
        migration = importlib.import_module(
            "apps.warehouse.migrations.0006_warehouse_default_receiving_location"
        )
        one = Warehouse.objects.create(
            department=Department.objects.create(name="MIG-ONE"), code="one", name="Один"
        )
        selected = StorageLocation.objects.create(
            warehouse=one, code="A", name="Единственный"
        )
        many = Warehouse.objects.create(
            department=Department.objects.create(name="MIG-MANY"), code="many", name="Несколько"
        )
        StorageLocation.objects.create(warehouse=many, code="A", name="Первый")
        StorageLocation.objects.create(warehouse=many, code="B", name="Второй")

        class Apps:
            @staticmethod
            def get_model(app_label, model_name):
                return {"Warehouse": Warehouse, "StorageLocation": StorageLocation}[model_name]

        migration.populate_unambiguous_defaults(Apps(), None)
        one.refresh_from_db()
        many.refresh_from_db()
        self.assertEqual(one.default_receiving_location_id, selected.pk)
        self.assertIsNone(many.default_receiving_location_id)


pytestmark = pytest.mark.integration
