from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import resolve_url
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.core.contract_store import _reset_for_tests
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
    WarehouseReportProfile,
)


GIT_ROLE_RULES = Path(settings.BASE_DIR) / "contracts" / "role_rules.json"


@override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=GIT_ROLE_RULES)
class WarehouseViewSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Department.objects.create(name="SEC-ORG")
        cls.own = Department.objects.create(name="SEC-OWN", parent=cls.organization)
        cls.child = Department.objects.create(name="SEC-CHILD", parent=cls.own)
        cls.sibling = Department.objects.create(name="SEC-FOREIGN", parent=cls.organization)

        for role_name in (
            "warehouse_operator",
            "warehouse_controller",
            "warehouse_administrator",
        ):
            Group.objects.create(name=role_name)

        cls.operator = cls._create_user("sec-operator", cls.own, "warehouse_operator")
        cls.controller = cls._create_user(
            "sec-controller", cls.own, "warehouse_controller"
        )
        cls.administrator = cls._create_user(
            "sec-administrator", cls.own, "warehouse_administrator"
        )
        cls.roleless = cls._create_user("sec-roleless", cls.own)
        cls.inactive = cls._create_user(
            "sec-inactive", cls.own, "warehouse_operator", is_active=False
        )
        cls.superuser = cls._create_user(
            "sec-root", cls.own, is_staff=True, is_superuser=True
        )

        cls.own_warehouse = Warehouse.objects.create(
            department=cls.own, code="SEC-OWN-WH", name="SEC-OWN-WAREHOUSE"
        )
        cls.child_warehouse = Warehouse.objects.create(
            department=cls.child, code="SEC-CHILD-WH", name="SEC-CHILD-WAREHOUSE"
        )
        cls.foreign_warehouse = Warehouse.objects.create(
            department=cls.sibling,
            code="SEC-FOREIGN-WH",
            name="SEC-FOREIGN-WAREHOUSE",
        )
        cls.own_location = StorageLocation.objects.create(
            warehouse=cls.own_warehouse,
            code="SEC-OWN-LOC",
            name="SEC-OWN-LOCATION",
        )
        cls.child_location = StorageLocation.objects.create(
            warehouse=cls.child_warehouse,
            code="SEC-CHILD-LOC",
            name="SEC-CHILD-LOCATION",
        )
        cls.foreign_location = StorageLocation.objects.create(
            warehouse=cls.foreign_warehouse,
            code="SEC-FOREIGN-LOC",
            name="SEC-FOREIGN-LOCATION",
        )

        cls.category = WarehouseItemCategory.objects.create(
            code="SEC-CAT", name="SEC-CATEGORY"
        )
        cls.unit = UnitOfMeasure.objects.create(
            code="SEC-PCS", name="SEC-PCS", quantity_precision=0
        )
        cls.funding = FundingSource.objects.create(
            code="SEC-FUND", name="SEC-FUNDING"
        )
        cls.own_item = WarehouseItem.objects.create(
            code="SEC-OWN-ITEM",
            name="SEC-OWN-REPORT-ITEM",
            category=cls.category,
            unit=cls.unit,
        )
        cls.child_item = WarehouseItem.objects.create(
            code="SEC-CHILD-ITEM",
            name="SEC-CHILD-REPORT-ITEM",
            category=cls.category,
            unit=cls.unit,
        )
        cls.foreign_item = WarehouseItem.objects.create(
            code="SEC-FOREIGN-ITEM",
            name="SEC-FOREIGN-REPORT-ITEM",
            category=cls.category,
            unit=cls.unit,
        )
        cls.expiry = date.today() + timedelta(days=365)

        cls.own_posted = cls._create_posted_receipt(
            department=cls.own,
            warehouse=cls.own_warehouse,
            location=cls.own_location,
            item=cls.own_item,
            series="SEC-OWN-SERIES",
            number="SEC-OWN-POSTED",
        )
        cls.child_posted = cls._create_posted_receipt(
            department=cls.child,
            warehouse=cls.child_warehouse,
            location=cls.child_location,
            item=cls.child_item,
            series="SEC-CHILD-SERIES",
            number="SEC-CHILD-POSTED",
        )
        cls.foreign_posted = cls._create_posted_receipt(
            department=cls.sibling,
            warehouse=cls.foreign_warehouse,
            location=cls.foreign_location,
            item=cls.foreign_item,
            series="SEC-FOREIGN-SERIES",
            number="SEC-FOREIGN-POSTED",
        )

        cls.own_draft = cls._create_draft(cls.own, "SEC-OWN-DRAFT")
        cls.child_draft = cls._create_draft(cls.child, "SEC-CHILD-DRAFT")
        cls.foreign_draft = cls._create_draft(cls.sibling, "SEC-FOREIGN-DRAFT")

        cls.own_profile = WarehouseReportProfile.objects.create(
            department=cls.own,
            name="SEC-OWN-PROFILE",
            created_by=cls.superuser,
        )
        cls.foreign_profile = WarehouseReportProfile.objects.create(
            department=cls.sibling,
            name="SEC-FOREIGN-PROFILE",
            created_by=cls.superuser,
        )

    @classmethod
    def _create_user(cls, username, department, role_name=None, **flags):
        user = get_user_model().objects.create_user(
            username=username, department=department, **flags
        )
        if role_name:
            user.groups.add(Group.objects.get(name=role_name))
        return user

    @classmethod
    def _create_draft(cls, department, number):
        return StockDocument.objects.create(
            department=department,
            document_type=StockDocument.DocumentType.RECEIPT,
            operation_date=date.today(),
            number=number,
            created_by=cls.superuser,
        )

    @classmethod
    def _create_posted_receipt(
        cls, *, department, warehouse, location, item, series, number
    ):
        document = StockDocument.objects.create(
            department=department,
            document_type=StockDocument.DocumentType.RECEIPT,
            operation_date=date.today(),
            number=number,
            created_by=cls.superuser,
        )
        line = StockDocumentLine.objects.create(
            document=document,
            sequence=1,
            item=item,
            series=series,
            expires_on=cls.expiry,
            funding_source=cls.funding,
            quantity=5,
            destination_location=location,
        )
        StockDocument.objects.filter(pk=document.pk).update(
            status=StockDocument.Status.POSTED,
            posted_by=cls.superuser,
        )
        document.refresh_from_db()
        StockEntry.objects.create(
            document=document,
            document_line=line,
            department=department,
            warehouse=warehouse,
            location=location,
            item=item,
            series=series,
            series_key=series.casefold(),
            expires_on=cls.expiry,
            unit=cls.unit,
            funding_source=cls.funding,
            quantity=5,
            operation_date=document.operation_date,
        )
        StockBalance.objects.create(
            department=department,
            warehouse=warehouse,
            location=location,
            item=item,
            series=series,
            series_key=series.casefold(),
            expires_on=cls.expiry,
            funding_source=cls.funding,
            quantity=5,
        )
        return document

    def setUp(self):
        _reset_for_tests()

    def tearDown(self):
        _reset_for_tests()

    def _login(self, actor, *, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        client.force_login(actor)
        return client

    def _document_post_data(self, *, department, destination):
        return {
            "department": str(department.pk),
            "document_type": StockDocument.DocumentType.RECEIPT,
            "number": "SEC-TAMPERED-DRAFT",
            "operation_date": date.today().isoformat(),
            "comment": "",
            "reason": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-sequence": "1",
            "lines-0-item": str(self.own_item.pk),
            "lines-0-series": "SEC-NEW-SERIES",
            "lines-0-expires_on": (date.today() + timedelta(days=180)).isoformat(),
            "lines-0-incomplete_reason": "",
            "lines-0-funding_source": str(self.funding.pk),
            "lines-0-quantity": "1",
            "lines-0-source_location": "",
            "lines-0-destination_location": str(destination.pk),
            "lines-0-fefo_override_reason": "",
        }

    def test_anonymous_routes_redirect_to_login(self):
        requests = (
            ("get", reverse("warehouse:overview")),
            ("get", reverse("warehouse:report_availability")),
            ("post", reverse("warehouse:document_post", args=[self.own_draft.pk])),
        )
        for method, url in requests:
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(resolve_url(settings.LOGIN_URL)))

    def test_roleless_user_gets_403_and_has_no_navigation_entry(self):
        client = self._login(self.roleless)
        self.assertEqual(client.get(reverse("warehouse:overview")).status_code, 403)
        self.assertEqual(client.get(reverse("warehouse:stock")).status_code, 403)
        self.assertEqual(
            client.get(reverse("warehouse:report_availability")).status_code, 403
        )
        dashboard = client.get(reverse("core:dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotContains(dashboard, reverse("warehouse:overview"))

    def test_operator_get_scope_includes_own_branch_and_excludes_foreign_objects(self):
        client = self._login(self.operator)

        overview = client.get(reverse("warehouse:overview"))
        self.assertEqual(overview.status_code, 200)
        self.assertContains(overview, "SEC-OWN-REPORT-ITEM")
        self.assertContains(overview, "SEC-CHILD-REPORT-ITEM")
        self.assertNotContains(overview, "SEC-FOREIGN-REPORT-ITEM")

        documents = client.get(reverse("warehouse:documents"))
        self.assertContains(documents, "SEC-OWN-DRAFT")
        self.assertContains(documents, "SEC-CHILD-DRAFT")
        self.assertNotContains(documents, "SEC-FOREIGN-DRAFT")
        self.assertEqual(
            client.get(
                reverse("warehouse:document_detail", args=[self.foreign_draft.pk])
            ).status_code,
            404,
        )

        form = client.get(reverse("warehouse:document_new"))
        self.assertEqual(form.status_code, 200)
        # Growing scoped choices are loaded through autocomplete rather than
        # embedded into the document form.  Verify the actual read boundary.
        departments = client.get(
            reverse("warehouse:autocomplete_department"), {"q": "SEC"}
        ).json()["results"]
        department_labels = {row["label"] for row in departments}
        self.assertIn("SEC-OWN", department_labels)
        self.assertIn("SEC-CHILD", department_labels)
        self.assertNotIn("SEC-FOREIGN", department_labels)

        locations = client.get(
            reverse("warehouse:autocomplete_location"),
            {"q": "SEC", "operation": "receipt"},
        ).json()["results"]
        location_labels = {row["label"] for row in locations}
        self.assertIn("SEC-OWN-LOC", location_labels)
        self.assertIn("SEC-CHILD-LOC", location_labels)
        self.assertNotIn("SEC-FOREIGN-LOC", location_labels)

    def test_operator_post_tampering_cannot_select_foreign_department_or_location(self):
        client = self._login(self.operator)
        initial_count = StockDocument.objects.count()

        foreign_department = client.post(
            reverse("warehouse:document_new"),
            self._document_post_data(
                department=self.sibling, destination=self.foreign_location
            ),
        )
        self.assertEqual(foreign_department.status_code, 400)
        self.assertEqual(StockDocument.objects.count(), initial_count)

        foreign_location = client.post(
            reverse("warehouse:document_new"),
            self._document_post_data(
                department=self.own, destination=self.foreign_location
            ),
        )
        self.assertEqual(foreign_location.status_code, 400)
        self.assertEqual(StockDocument.objects.count(), initial_count)

    def test_series_is_entered_in_document_without_registration_screen(self):
        client = self._login(self.operator)
        response = client.post(
            reverse("warehouse:document_new"),
            self._document_post_data(
                department=self.child,
                destination=self.child_location,
            ),
        )

        self.assertEqual(response.status_code, 302)
        line = StockDocumentLine.objects.get(document__number="SEC-TAMPERED-DRAFT")
        self.assertEqual(line.series, "SEC-NEW-SERIES")
        self.assertEqual(line.series_key, "sec-new-series")
        overview = client.get(reverse("warehouse:overview"))
        self.assertNotContains(overview, "Зарегистрировать партию")

    def test_operator_has_no_controller_or_catalog_routes(self):
        client = self._login(self.operator)
        for url in (
            reverse("warehouse:warehouses"),
            reverse("warehouse:locations"),
            reverse("warehouse:report_profiles"),
            reverse("warehouse:catalog", args=["items"]),
        ):
            self.assertEqual(client.get(url).status_code, 403)

    def test_controller_can_adjust_and_manage_branch_locations_and_profiles(self):
        client = self._login(self.controller)

        document_form = client.get(reverse("warehouse:document_new"))
        self.assertEqual(document_form.status_code, 200)
        self.assertContains(document_form, 'value="adjustment"')
        self.assertContains(document_form, 'value="writeoff"')
        adjustment_data = self._document_post_data(
            department=self.child, destination=self.child_location
        )
        adjustment_data.update(
            {
                "document_type": StockDocument.DocumentType.ADJUSTMENT,
                "number": "SEC-CONTROLLER-ADJUSTMENT",
                "reason": "SEC-CONTROLLED-REASON",
            }
        )
        adjustment = client.post(reverse("warehouse:document_new"), adjustment_data)
        self.assertEqual(adjustment.status_code, 302)
        self.assertTrue(
            StockDocument.objects.filter(number="SEC-CONTROLLER-ADJUSTMENT").exists()
        )

        locations = client.get(reverse("warehouse:locations"))
        self.assertEqual(locations.status_code, 200)
        self.assertContains(locations, "SEC-OWN-LOC")
        self.assertContains(locations, "SEC-CHILD-LOC")
        self.assertNotContains(locations, "SEC-FOREIGN-LOC")
        self.assertEqual(
            client.get(
                reverse("warehouse:location_edit", args=[self.foreign_location.pk])
            ).status_code,
            404,
        )
        created_location = client.post(
            reverse("warehouse:locations"),
            {
                "warehouse": self.child_warehouse.pk,
                "code": "SEC-CONTROLLER-LOC",
                "name": "SEC-CONTROLLER-LOCATION",
                "location_type": StorageLocation.LocationType.RACK,
                "purpose": StorageLocation.Purpose.AVAILABLE,
                "sort_order": 10,
                "is_active": "on",
            },
        )
        self.assertEqual(created_location.status_code, 302)
        self.assertTrue(
            StorageLocation.objects.filter(code="SEC-CONTROLLER-LOC").exists()
        )

        profiles = client.get(reverse("warehouse:report_profiles"))
        self.assertEqual(profiles.status_code, 200)
        self.assertContains(profiles, "SEC-OWN-PROFILE")
        self.assertNotContains(profiles, "SEC-FOREIGN-PROFILE")
        created_profile = client.post(
            reverse("warehouse:report_profiles"),
            {
                "department": self.child.pk,
                "name": "SEC-CONTROLLER-PROFILE",
                "valid_from": "",
                "valid_to": "",
                "approval_label": "",
                "signer_position": "",
                "signer_name": "",
                "footer_note": "",
                "is_active": "on",
            },
        )
        self.assertEqual(created_profile.status_code, 302)
        self.assertTrue(
            WarehouseReportProfile.objects.filter(
                name="SEC-CONTROLLER-PROFILE", department=self.child
            ).exists()
        )

    def test_controller_post_tampering_cannot_manage_foreign_location_or_profile(self):
        client = self._login(self.controller)
        location_name = self.foreign_location.name
        response = client.post(
            reverse("warehouse:location_edit", args=[self.foreign_location.pk]),
            {
                "warehouse": self.foreign_warehouse.pk,
                "code": self.foreign_location.code,
                "name": "SEC-FOREIGN-LOCATION-TAMPERED",
                "location_type": StorageLocation.LocationType.RACK,
                "purpose": StorageLocation.Purpose.AVAILABLE,
                "sort_order": 0,
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.foreign_location.refresh_from_db()
        self.assertEqual(self.foreign_location.name, location_name)

        profile_name = self.foreign_profile.name
        response = client.post(
            reverse("warehouse:report_profile_edit", args=[self.foreign_profile.pk]),
            {
                "department": self.sibling.pk,
                "name": "SEC-FOREIGN-PROFILE-TAMPERED",
                "valid_from": "",
                "valid_to": "",
                "approval_label": "",
                "signer_position": "",
                "signer_name": "",
                "footer_note": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.foreign_profile.refresh_from_db()
        self.assertEqual(self.foreign_profile.name, profile_name)

    def test_administrator_has_global_read_and_catalog_but_no_document_operations(self):
        client = self._login(self.administrator)

        overview = client.get(reverse("warehouse:overview"))
        self.assertContains(overview, "SEC-OWN-REPORT-ITEM")
        self.assertContains(overview, "SEC-FOREIGN-REPORT-ITEM")
        documents = client.get(reverse("warehouse:documents"))
        self.assertContains(documents, "SEC-FOREIGN-DRAFT")
        stock = client.get(reverse("warehouse:stock"))
        self.assertEqual(stock.status_code, 200)
        self.assertContains(stock, "SEC-FOREIGN-REPORT-ITEM")
        self.assertNotContains(stock, "data-relocation-selection")
        self.assertNotContains(stock, "Переместить")
        self.assertEqual(client.get(reverse("warehouse:document_new")).status_code, 403)

        catalog = client.get(reverse("warehouse:catalog", args=["categories"]))
        self.assertEqual(catalog.status_code, 200)
        created = client.post(
            reverse("warehouse:catalog", args=["categories"]),
            {"code": "SEC-ADMIN-CAT", "name": "SEC-ADMIN-CATEGORY", "is_active": "on"},
        )
        self.assertEqual(created.status_code, 302)
        self.assertTrue(
            WarehouseItemCategory.objects.filter(code="SEC-ADMIN-CAT").exists()
        )

        self.assertEqual(
            client.post(
                reverse("warehouse:document_post", args=[self.own_draft.pk])
            ).status_code,
            403,
        )

    def test_mixed_view_and_operate_scopes_show_only_operable_row_controls(self):
        mixed = self._create_user("sec-mixed", self.own)
        mixed.groups.add(
            Group.objects.get(name="warehouse_administrator"),
            Group.objects.get(name="warehouse_operator"),
        )
        client = self._login(mixed)
        response = client.get(reverse("warehouse:stock"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SEC-FOREIGN-REPORT-ITEM")
        self.assertContains(response, 'data-relocation-selection')
        # Own and child balances are operable; the globally visible foreign
        # balance is intentionally rendered read-only.
        self.assertEqual(response.content.decode().count('data-relocation-select>'), 2)
        self.assertEqual(
            client.post(
                reverse("warehouse:document_reverse", args=[self.own_posted.pk]),
                {"operation_date": date.today().isoformat(), "reason": "SEC-DENIED"},
            ).status_code,
            403,
        )

    def test_report_profile_department_provider_uses_management_scope(self):
        operator_client = self._login(self.operator)
        self.assertEqual(
            operator_client.get(
                reverse("warehouse:autocomplete_report_profile_department"),
                {"q": "SEC"},
            ).status_code,
            403,
        )

        controller_client = self._login(self.controller)
        response = controller_client.get(
            reverse("warehouse:autocomplete_report_profile_department"),
            {"q": "SEC"},
        )
        self.assertEqual(response.status_code, 200)
        values = {row["value"] for row in response.json()["results"]}
        self.assertIn(str(self.own.pk), values)
        self.assertIn(str(self.child.pk), values)
        self.assertNotIn(str(self.sibling.pk), values)

    def test_item_form_preserves_current_archived_category_and_unit(self):
        from apps.warehouse.forms import WarehouseItemForm

        category = WarehouseItemCategory.objects.create(
            code="SEC-ARCHIVE-CAT",
            name="SEC-ARCHIVE-CATEGORY",
            is_active=False,
        )
        unit = UnitOfMeasure.objects.create(
            code="SEC-ARCHIVE-UNIT",
            name="SEC-ARCHIVE-UNIT",
            quantity_precision=0,
            is_active=False,
        )
        item = WarehouseItem.objects.create(
            code="SEC-ARCHIVE-ITEM",
            name="SEC-ARCHIVE-ITEM",
            category=category,
            unit=unit,
        )
        form = WarehouseItemForm(
            {
                "code": item.code,
                "name": item.name,
                "short_name": "",
                "category": category.pk,
                "unit": unit.pk,
                "manufacturer": "",
                "dosage_form": "",
                "application_method": "",
                "is_active": "on",
            },
            actor=self.administrator,
            instance=item,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_stock_pagination_serializes_legacy_item_once(self):
        from apps.warehouse.relocation_selectors import sanitized_stock_filter_query

        query = sanitized_stock_filter_query(
            {"item": "SEC-ITEM", "series": "SEC-SERIES", "page": "2"}
        )
        self.assertEqual(query.count("item="), 1)
        self.assertNotIn("page=", query)

    def test_inactive_user_is_denied_and_navigation_is_hidden(self):
        client = self._login(self.inactive)
        # ModelBackend intentionally resolves an inactive session as anonymous.
        # The public fail-closed result is therefore a login redirect, not a 403.
        warehouse = client.get(reverse("warehouse:overview"))
        self.assertEqual(warehouse.status_code, 302)
        self.assertTrue(warehouse.url.startswith(resolve_url(settings.LOGIN_URL)))
        dashboard = client.get(reverse("core:dashboard"))
        self.assertEqual(dashboard.status_code, 302)
        self.assertTrue(dashboard.url.startswith(resolve_url(settings.LOGIN_URL)))

    def test_superuser_has_all_warehouse_routes_and_foreign_data(self):
        client = self._login(self.superuser)
        for url in (
            reverse("warehouse:overview"),
            reverse("warehouse:document_new"),
            reverse("warehouse:warehouses"),
            reverse("warehouse:locations"),
            reverse("warehouse:report_profiles"),
            reverse("warehouse:catalog", args=["items"]),
        ):
            self.assertEqual(client.get(url).status_code, 200)
        overview = client.get(reverse("warehouse:overview"))
        self.assertContains(overview, "SEC-FOREIGN-REPORT-ITEM")

    def test_catalog_list_search_and_pagination_are_bounded(self):
        for index in range(60):
            WarehouseItemCategory.objects.create(
                code=f"SEC-PAGE-CAT-{index:03d}",
                name=f"SEC-PAGE-CATEGORY-{index:03d}",
            )
        client = self._login(self.superuser)
        first_page = client.get(
            reverse("warehouse:catalog", args=["categories"]),
            {"q": "SEC-PAGE-CATEGORY", "page": 1},
        )
        self.assertEqual(first_page.status_code, 200)
        self.assertContains(first_page, "Найдено: 60")
        self.assertContains(first_page, "SEC-PAGE-CAT-000")
        self.assertNotContains(first_page, "SEC-PAGE-CAT-059")
        second_page = client.get(
            reverse("warehouse:catalog", args=["categories"]),
            {"q": "SEC-PAGE-CATEGORY", "page": 2},
        )
        self.assertContains(second_page, "SEC-PAGE-CAT-059")
        self.assertContains(second_page, "q=SEC-PAGE-CATEGORY")

    def test_html_csv_and_xlsx_reports_use_the_same_operator_scope(self):
        client = self._login(self.operator)
        url = reverse("warehouse:report_availability")

        html = client.get(url)
        self.assertEqual(html.status_code, 200)
        self.assertContains(html, "SEC-OWN-REPORT-ITEM")
        self.assertContains(html, "SEC-CHILD-REPORT-ITEM")
        self.assertNotContains(html, "SEC-FOREIGN-REPORT-ITEM")

        csv_response = client.get(url, {"format": "csv"})
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        csv_text = csv_response.content.decode("utf-8-sig")
        self.assertIn("SEC-OWN-REPORT-ITEM", csv_text)
        self.assertIn("SEC-CHILD-REPORT-ITEM", csv_text)
        self.assertNotIn("SEC-FOREIGN-REPORT-ITEM", csv_text)

        xlsx_response = client.get(url, {"format": "xlsx"})
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertEqual(
            xlsx_response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        with ZipFile(BytesIO(xlsx_response.content)) as archive:
            xml = "\n".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith(".xml")
            )
        self.assertIn("SEC-OWN-REPORT-ITEM", xml)
        self.assertIn("SEC-CHILD-REPORT-ITEM", xml)
        self.assertNotIn("SEC-FOREIGN-REPORT-ITEM", xml)

    def test_report_url_keeps_profile_metadata_for_single_department(self):
        client = self._login(self.operator)
        response = client.get(
            reverse("warehouse:report_availability"),
            {"department_id": self.own.pk, "location_purpose": "available"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SEC-OWN-PROFILE")

    def test_all_production_report_urls_accept_empty_query(self):
        client = self._login(self.operator)
        for name in ("report_expense", "report_rack_card", "report_availability"):
            response = client.get(reverse(f"warehouse:{name}"))
            self.assertEqual(response.status_code, 200, name)

    def test_post_action_requires_csrf_token_and_accepts_a_valid_token(self):
        document = self._create_draft(self.own, "SEC-CSRF-DRAFT")
        client = self._login(self.operator, csrf=True)
        detail = client.get(reverse("warehouse:document_detail", args=[document.pk]))
        self.assertEqual(detail.status_code, 200)
        csrf_token = client.cookies["csrftoken"].value

        rejected = client.post(
            reverse("warehouse:document_cancel", args=[document.pk]),
            {"reason": "SEC-CSRF-CANCEL"},
        )
        self.assertEqual(rejected.status_code, 403)
        document.refresh_from_db()
        self.assertEqual(document.status, StockDocument.Status.DRAFT)

        accepted = client.post(
            reverse("warehouse:document_cancel", args=[document.pk]),
            {"reason": "SEC-CSRF-CANCEL"},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(accepted.status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.status, StockDocument.Status.CANCELLED)
pytestmark = pytest.mark.integration
