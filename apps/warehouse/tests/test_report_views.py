from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory
from django.core.exceptions import PermissionDenied

import pytest

from apps.warehouse.report_forms import WarehouseReportFilterForm, filter_report_rows
from apps.warehouse.report_views import report_view
from apps.warehouse.reports.datasets import ReportTooLargeError
from apps.warehouse.reports.exports import format_quantity, prepare_export_rows

pytestmark = pytest.mark.unit


def test_quantity_uses_unit_precision():
    assert format_quantity(Decimal("2.50"), 0) == "2"
    assert format_quantity(Decimal("2.5"), 2) == "2.50"


def test_filter_report_rows_separates_expired_and_unassigned():
    rows = [
        {"item": "A", "expires_on": date(2026, 1, 1), "department_id": 1},
        {"item": "B", "expires_on": None, "department_id": 1},
    ]
    assert [row["item"] for row in filter_report_rows(rows, {"expiry_state": "expired", "as_of": date(2026, 2, 1)})] == ["A"]
    assert [row["item"] for row in filter_report_rows(rows, {"expiry_state": "none", "as_of": date(2026, 2, 1)})] == ["B"]


def test_filter_report_rows_uses_distinct_configured_expiry_bands():
    rows = [
        {"item": "A", "expires_on": date(2026, 1, 11)},  # 10 days
        {"item": "B", "expires_on": date(2026, 2, 15)},  # 45 days
        {"item": "C", "expires_on": date(2026, 4, 11)},  # 100 days
        {"item": "D", "expires_on": date(2026, 8, 1)},   # 212 days
    ]
    cleaned = {"as_of": date(2026, 1, 1)}
    assert [row["item"] for row in filter_report_rows(rows, {**cleaned, "expiry_state": "due_30"}, expiry_warning_days=[30, 90, 180])] == ["A"]
    assert [row["item"] for row in filter_report_rows(rows, {**cleaned, "expiry_state": "due_90"}, expiry_warning_days=[30, 90, 180])] == ["B"]
    assert [row["item"] for row in filter_report_rows(rows, {**cleaned, "expiry_state": "due_180"}, expiry_warning_days=[30, 90, 180])] == ["C"]
    assert [row["item"] for row in filter_report_rows(rows, {**cleaned, "expiry_state": "valid"}, expiry_warning_days=[30, 90, 180])] == ["D"]


def test_expense_filter_form_does_not_expose_stock_dimensions(monkeypatch):
    monkeypatch.setattr(
        "apps.warehouse.report_forms.department_ids_for_warehouse_scope",
        lambda *args, **kwargs: set(),
    )
    monkeypatch.setattr("apps.warehouse.report_forms.Department.objects.filter", lambda *args, **kwargs: [])
    form = WarehouseReportFilterForm({}, actor=None, period=True)
    assert set(form.fields) == {"search", "department_id", "start", "end"}


def test_stock_filter_form_exposes_expiry_bands(monkeypatch):
    monkeypatch.setattr(
        "apps.warehouse.report_forms.department_ids_for_warehouse_scope",
        lambda *args, **kwargs: set(),
    )
    monkeypatch.setattr("apps.warehouse.report_forms.Department.objects.filter", lambda *args, **kwargs: [])
    form = WarehouseReportFilterForm({}, actor=None, period=False, expiry_warning_days=[30, 90, 180])
    assert [value for value, _ in form.fields["expiry_state"].choices] == ["", "expired", "due_30", "due_90", "due_180", "valid", "none"]


def test_export_rows_hide_technical_ids_and_use_russian_labels():
    rows = [{"item_id": 3, "item": "A", "quantity": Decimal("2"), "quantity_precision": 0}]
    exported = prepare_export_rows(rows)
    assert exported == [{"Наименование": "A", "Остаток": "2"}]


@pytest.mark.django_db
def test_report_view_keeps_filters_and_export_semantics():
    row = {"department_id": 1, "item_id": 3, "item": "A", "unit": "шт.", "quantity": Decimal("2"), "quantity_precision": 0, "location_purpose": "quarantine"}
    factory = RequestFactory()
    actor = SimpleNamespace(is_authenticated=False)
    requests = [factory.get("/reports", params) for params in ({"location_purpose": "quarantine"}, {"location_purpose": "quarantine", "format": "csv"}, {"location_purpose": "quarantine", "format": "xlsx"})]
    for request in requests:
        request.user = actor
    with patch("apps.warehouse.report_views.build_rack_card", return_value=[row]), patch("apps.warehouse.report_views.get_warehouse_runtime_settings", return_value={"expiry_warning_days": [30, 90], "default_quantity_precision": 0}):
        html, csv, xlsx = [report_view(request, report_kind="rack-card", actor=actor, department_ids={1}) for request in requests]
    assert "Наименование" in html.content.decode()
    assert "Карантин" in csv.content.decode("utf-8-sig")
    assert xlsx["Content-Type"].startswith("application/vnd.openxmlformats")


def test_report_view_denies_empty_scope():
    with pytest.raises(PermissionDenied):
        report_view(RequestFactory().get("/reports"), report_kind="rack-card", actor=None, department_ids=set())


@pytest.mark.django_db
def test_report_view_returns_visible_guard_when_aggregate_is_too_large():
    request = RequestFactory().get("/reports/availability/")
    request.user = SimpleNamespace(is_authenticated=False)
    with patch("apps.warehouse.report_views.build_department_availability", side_effect=ReportTooLargeError("too large")):
        response = report_view(request, report_kind="availability", actor=request.user, department_ids={1})
    assert response.status_code == 413
    assert "10,000" in response.content.decode()


@pytest.mark.django_db
def test_report_filter_errors_keep_values_in_html():
    factory = RequestFactory()
    request = factory.get(
        "/reports",
        {"start": "2026-08-31", "end": "2026-08-01", "search": "Ампула"},
    )
    request.user = SimpleNamespace(is_authenticated=False)
    response = report_view(
        request, report_kind="expense", actor=request.user, department_ids={1}
    )
    assert response.status_code == 422
    body = response.content.decode()
    assert "2026-08-31" in body
    assert "Дата окончания не может быть раньше" in body
