from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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
from apps.warehouse.services import post_document


pytestmark = pytest.mark.integration


class WarehouseDocumentSidebarTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Sidebar department")
        self.actor = get_user_model().objects.create_superuser(
            username="sidebar-user", password="password", department=self.department
        )
        self.client.force_login(self.actor)
        category = WarehouseItemCategory.objects.create(code="sidebar-cat", name="Category")
        unit = UnitOfMeasure.objects.create(code="sidebar-unit", name="pcs", quantity_precision=0)
        self.funding = FundingSource.objects.create(code="sidebar-funding", name="Funding")
        self.items = [
            WarehouseItem.objects.create(code=f"sidebar-item-{n}", name=f"Sidebar item {n}", category=category, unit=unit)
            for n in range(1, 4)
        ]
        warehouse = Warehouse.objects.create(department=self.department, code="sidebar-wh", name="Main")
        self.location = StorageLocation.objects.create(warehouse=warehouse, code="R-1", name="Rack 1")

    def _post_data(self, *, invalid_second=False, action="save", initial_forms=0, lines=None):
        data = {
            "department": self.department.pk,
            "document_type": StockDocument.DocumentType.RECEIPT,
            "operation_date": date.today().isoformat(),
            "number": "SIDEBAR-DRAFT",
            "comment": "",
            "reason": "",
            "idempotency_key": str(uuid4()),
            "action": action,
            "lines-TOTAL_FORMS": "3",
            "lines-INITIAL_FORMS": str(initial_forms),
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
        }
        for index, item in enumerate(self.items):
            data.update(
                {
                    f"lines-{index}-item": item.pk,
                    f"lines-{index}-series": f"S-{index + 1}",
                    f"lines-{index}-expires_on": (date.today() + timedelta(days=365)).isoformat(),
                    f"lines-{index}-funding_source": self.funding.pk,
                    f"lines-{index}-quantity": "1",
                    f"lines-{index}-destination_location": self.location.pk,
                    f"lines-{index}-sequence": "999",
                }
            )
            if lines and index < len(lines):
                data[f"lines-{index}-id"] = lines[index].pk
        if invalid_second:
            data["lines-1-quantity"] = "0"
        return data

    def test_panel_get_contains_tabular_editor_and_hidden_sequence(self):
        response = self.client.get(reverse("warehouse:document_new_panel"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-document-lines-table")
        self.assertContains(response, "Сохранить черновик")
        self.assertContains(response, "name=\"lines-0-sequence\"")
        self.assertContains(response, "data-autocomplete")

    def test_panel_post_creates_all_rows_and_server_assigns_sequence(self):
        response = self.client.post(
            reverse("warehouse:document_new_panel"), self._post_data(), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        document = StockDocument.objects.get(number="SIDEBAR-DRAFT")
        self.assertEqual(list(document.lines.values_list("sequence", flat=True)), [1, 2, 3])
        self.assertContains(response, "Документ сохранён")
        for event_name in ("rightPanelFormSucceeded", "warehouseDocumentsChanged", "warehouseStockChanged"):
            self.assertIn(event_name, response["HX-Trigger"])

    def test_create_is_idempotent_and_emits_all_refresh_events(self):
        data = self._post_data()
        response = self.client.post(reverse("warehouse:document_new_panel"), data, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        data["number"] = "SHOULD-NOT-DUPLICATE"
        replay = self.client.post(reverse("warehouse:document_new_panel"), data, HTTP_HX_REQUEST="true")
        self.assertEqual(replay.status_code, 409)
        data["number"] = "SIDEBAR-DRAFT"
        replay = self.client.post(reverse("warehouse:document_new_panel"), data, HTTP_HX_REQUEST="true")
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(StockDocument.objects.filter(idempotency_key=data["idempotency_key"]).count(), 1)
        self.assertIn("warehouseDocumentsChanged", response["HX-Trigger"])
        self.assertIn("warehouseStockChanged", response["HX-Trigger"])

    def test_edit_panel_updates_draft_and_provider_is_scoped_transport(self):
        create = self.client.post(reverse("warehouse:document_new_panel"), self._post_data(), HTTP_HX_REQUEST="true")
        document = StockDocument.objects.get(number="SIDEBAR-DRAFT")
        lines = list(StockDocumentLine.objects.filter(document=document).order_by("sequence"))
        data = self._post_data(initial_forms=3, lines=lines)
        data["number"] = "SIDEBAR-EDITED"
        data["idempotency_key"] = ""
        response = self.client.post(reverse("warehouse:document_edit_panel", args=[document.pk]), data, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(StockDocument.objects.filter(pk=document.pk, number="SIDEBAR-EDITED").exists())
        options = self.client.get(reverse("warehouse:autocomplete_item"), {"q": "Sidebar item 1"})
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.json()["mode"], "entity")

    def test_panel_validation_returns_422_and_keeps_other_rows(self):
        response = self.client.post(
            reverse("warehouse:document_new_panel"),
            self._post_data(invalid_second=True),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Sidebar item 1", status_code=422)
        self.assertContains(response, "Sidebar item 3", status_code=422)
        self.assertEqual(StockDocument.objects.filter(number="SIDEBAR-DRAFT").count(), 0)

    def test_posted_document_has_no_edit_panel(self):
        document = StockDocument.objects.create(
            department=self.department,
            document_type=StockDocument.DocumentType.RECEIPT,
            operation_date=date.today(),
            created_by=self.actor,
        )
        StockDocumentLine.objects.create(
            document=document,
            item=self.items[0],
            series="POSTED",
            expires_on=date.today() + timedelta(days=365),
            funding_source=self.funding,
            quantity=1,
            destination_location=self.location,
        )
        post_document(document_id=document.pk, actor=self.actor)
        response = self.client.get(reverse("warehouse:document_edit_panel", args=[document.pk]))
        self.assertEqual(response.status_code, 404)
