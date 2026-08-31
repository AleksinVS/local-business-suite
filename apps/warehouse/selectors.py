"""Единые серверные селекторы складских данных по подразделениям."""
from __future__ import annotations

from django.db.models import QuerySet

from .models import (
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockEntry,
    StorageLocation,
    Warehouse,
    WarehouseReportProfile,
)
from .policies import (
    WAREHOUSE_ADJUST_SCOPE,
    WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
    WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
    WAREHOUSE_OPERATE_SCOPE,
    WAREHOUSE_VIEW_SCOPE,
    department_ids_for_warehouse_scope,
)


def _scoped_queryset(actor, queryset: QuerySet, *, capability: str, department_lookup: str):
    department_ids = department_ids_for_warehouse_scope(actor, capability)
    if department_ids is None:
        return queryset
    if not department_ids:
        return queryset.none()
    return queryset.filter(**{f"{department_lookup}__in": department_ids})


def warehouses_for_scope(
    actor,
    capability: str,
    *,
    queryset: QuerySet | None = None,
) -> QuerySet:
    """Склады в одной явно указанной складской области."""

    queryset = queryset if queryset is not None else Warehouse.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=capability,
        department_lookup="department_id",
    )


def visible_warehouses_queryset(actor, *, queryset: QuerySet | None = None) -> QuerySet:
    return warehouses_for_scope(actor, WAREHOUSE_VIEW_SCOPE, queryset=queryset)


def operable_warehouses_queryset(actor, *, queryset: QuerySet | None = None) -> QuerySet:
    return warehouses_for_scope(actor, WAREHOUSE_OPERATE_SCOPE, queryset=queryset)


def adjustable_warehouses_queryset(actor, *, queryset: QuerySet | None = None) -> QuerySet:
    return warehouses_for_scope(actor, WAREHOUSE_ADJUST_SCOPE, queryset=queryset)


def manageable_location_warehouses_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    return warehouses_for_scope(
        actor,
        WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
        queryset=queryset,
    )


def visible_locations_queryset(actor, *, queryset: QuerySet | None = None) -> QuerySet:
    queryset = queryset if queryset is not None else StorageLocation.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_VIEW_SCOPE,
        department_lookup="warehouse__department_id",
    )


def manageable_locations_queryset(actor, *, queryset: QuerySet | None = None) -> QuerySet:
    queryset = queryset if queryset is not None else StorageLocation.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
        department_lookup="warehouse__department_id",
    )


def visible_stock_documents_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    queryset = queryset if queryset is not None else StockDocument.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_VIEW_SCOPE,
        department_lookup="department_id",
    )


def visible_stock_document_lines_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    queryset = queryset if queryset is not None else StockDocumentLine.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_VIEW_SCOPE,
        department_lookup="document__department_id",
    )


def visible_stock_entries_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    queryset = queryset if queryset is not None else StockEntry.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_VIEW_SCOPE,
        department_lookup="department_id",
    )


def visible_stock_balances_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    queryset = queryset if queryset is not None else StockBalance.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_VIEW_SCOPE,
        department_lookup="department_id",
    )


def visible_report_profiles_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    queryset = queryset if queryset is not None else WarehouseReportProfile.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_VIEW_SCOPE,
        department_lookup="department_id",
    )


def manageable_report_profiles_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    queryset = queryset if queryset is not None else WarehouseReportProfile.objects.all()
    return _scoped_queryset(
        actor,
        queryset,
        capability=WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
        department_lookup="department_id",
    )
