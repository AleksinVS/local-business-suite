"""Warehouse-owned providers for the shared autocomplete transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from django.db.models import Q

from apps.core.autocomplete import AutocompleteOption, register_autocomplete_provider

from apps.core.models import Department
from .models import (
    FundingSource,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
)
from .policies import (
    WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
    WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
    WAREHOUSE_OPERATE_SCOPE,
    WAREHOUSE_VIEW_SCOPE,
    department_ids_for_warehouse_scope,
)
from .selectors import (
    manageable_location_warehouses_queryset,
    visible_locations_queryset,
    visible_stock_balances_queryset,
)
from .relocation_selectors import (
    visible_relocatable_stock_balances_queryset,
)


def _can_use(user) -> bool:
    return department_ids_for_warehouse_scope(user, WAREHOUSE_OPERATE_SCOPE) != set()


@dataclass(frozen=True)
class WarehouseDepartmentProvider:
    code: str = "warehouse.department"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user):
        return _can_use(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        ids = department_ids_for_warehouse_scope(user, WAREHOUSE_OPERATE_SCOPE)
        departments = Department.objects.all() if ids is None else Department.objects.filter(pk__in=ids)
        if query:
            departments = departments.filter(name__icontains=query)
        return [AutocompleteOption(value=department.pk, label=department.name) for department in departments.order_by("name", "id")[:limit]]


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class WarehouseItemProvider:
    code: str = "warehouse.item"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department",)
    result_limit: int = 20

    def can_use(self, user):
        return _can_use(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        items = WarehouseItem.objects.filter(is_active=True).select_related("unit").order_by("name", "id")
        if query:
            items = items.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(short_name__icontains=query))
        return [
            AutocompleteOption(value=item.pk, label=item.name, secondary=f"{item.code} · {item.unit}", metadata={"unit_label": str(item.unit), "unit_precision": item.unit.quantity_precision})
            for item in items[:limit]
        ]


@dataclass(frozen=True)
class WarehouseSourceProvider:
    code: str = "warehouse.source"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user):
        return _can_use(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        sources = FundingSource.objects.filter(is_active=True).order_by("name", "id")
        if query:
            sources = sources.filter(Q(name__icontains=query) | Q(code__icontains=query))
        return [AutocompleteOption(value=source.pk, label=source.name, secondary=source.code) for source in sources[:limit]]


@dataclass(frozen=True)
class WarehouseLocationProvider:
    code: str = "warehouse.location"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department", "operation", "item", "series", "source")
    result_limit: int = 20

    def can_use(self, user):
        return _can_use(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        locations = visible_locations_queryset(user).filter(is_active=True).select_related("warehouse", "warehouse__department")
        department_id = _int(context.get("department"))
        if department_id:
            locations = locations.filter(warehouse__department_id=department_id)
        # A document address must never point at a quarantine or unassigned
        # location.  Receipt/issue use the same available locations, while an
        # issue additionally requires a positive balance for the selected
        # item/series/source.  The final form/model validation remains the
        # authority at POST time.
        locations = locations.filter(purpose=StorageLocation.Purpose.AVAILABLE)
        operation = context.get("operation", "")
        if operation in {
            "issue",
            "writeoff",
        }:
            item_id = _int(context.get("item"))
            if item_id:
                balances = visible_stock_balances_queryset(user).filter(
                    item_id=item_id,
                    location__purpose=StorageLocation.Purpose.AVAILABLE,
                    location__is_active=True,
                    quantity__gt=0,
                )
                series = (context.get("series") or "").strip()
                source_id = _int(context.get("source"))
                if series:
                    # series_key is normalized server-side; retaining the
                    # case-insensitive fallback keeps typing suggestions
                    # useful while POST revalidation prevents forged values.
                    from apps.warehouse.series import normalize_series

                    try:
                        _, series_key = normalize_series(series)
                    except Exception:
                        series_key = series.casefold()
                    balances = balances.filter(series_key=series_key)
                if source_id:
                    balances = balances.filter(funding_source_id=source_id)
                locations = locations.filter(pk__in=balances.values("location_id"))
        if query:
            locations = locations.filter(Q(code__icontains=query) | Q(name__icontains=query) | Q(warehouse__name__icontains=query))
        return [AutocompleteOption(value=location.pk, label=location.code, secondary=f"{location.warehouse.name} · {location.name}", metadata={"warehouse_id": location.warehouse_id, "department_id": location.warehouse.department_id}) for location in locations[:limit]]


@dataclass(frozen=True)
class WarehouseSeriesProvider:
    code: str = "warehouse.series"
    mode: str = "suggestion"
    context_keys: tuple[str, ...] = ("item", "department")
    result_limit: int = 20

    def can_use(self, user):
        return _can_use(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        item_id = _int(context.get("item"))
        if not item_id:
            return []
        balances = visible_stock_balances_queryset(user).filter(item_id=item_id, series_key__gt="", quantity__gt=0, location__is_active=True, location__purpose=StorageLocation.Purpose.AVAILABLE).exclude(series="").select_related("location", "funding_source")
        department_id = _int(context.get("department"))
        if department_id:
            balances = balances.filter(department_id=department_id)
        if query:
            balances = balances.filter(series__icontains=query)
        seen = {}
        for row in balances.order_by("expires_on", "series_key", "id")[:limit]:
            expiry = row.expires_on
            metadata = {
                "expires_on": expiry.isoformat() if expiry else "",
                "source_location_id": row.location_id,
                "source_location_label": str(row.location),
                "funding_source_id": row.funding_source_id,
                "funding_source_label": str(row.funding_source),
                "available_quantity": str(row.quantity),
            }
            seen.setdefault(row.series_key, (row.series, expiry, metadata))
        return [AutocompleteOption(value=display, label=display, secondary=(f"до {expiry}" if expiry else ""), metadata=metadata) for display, expiry, metadata in list(seen.values())[:limit]]


@dataclass(frozen=True)
class WarehouseScopedDepartmentProvider:
    code: str
    capability: str
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user):
        return department_ids_for_warehouse_scope(user, self.capability) != set()

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        ids = department_ids_for_warehouse_scope(user, self.capability)
        departments = Department.objects.all() if ids is None else Department.objects.filter(pk__in=ids)
        if query:
            departments = departments.filter(name__icontains=query)
        return [AutocompleteOption(value=row.pk, label=row.name) for row in departments.order_by("name", "pk")[:limit]]


@dataclass(frozen=True)
class WarehouseFilterEntityProvider:
    code: str
    entity: str
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department_id", "warehouse_id", "category_id", "funding_source_id")
    result_limit: int = 20

    def can_use(self, user):
        return department_ids_for_warehouse_scope(user, WAREHOUSE_VIEW_SCOPE) != set()

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        balances = visible_relocatable_stock_balances_queryset(user)
        for key, lookup in (
            ("department_id", "department_id"),
            ("warehouse_id", "warehouse_id"),
            ("category_id", "item__category_id"),
            ("funding_source_id", "funding_source_id"),
        ):
            value = _int(context.get(key))
            if value:
                balances = balances.filter(**{lookup: value})
        if self.entity == "warehouse":
            values = Warehouse.objects.filter(pk__in=balances.values("warehouse_id"), is_active=True)
            if query:
                values = values.filter(Q(name__icontains=query) | Q(code__icontains=query))
            return [AutocompleteOption(value=row.pk, label=row.name, secondary=row.code) for row in values.order_by("name", "code", "pk")[:limit]]
        if self.entity == "location":
            values = StorageLocation.objects.filter(pk__in=balances.values("location_id"), is_active=True, purpose=StorageLocation.Purpose.AVAILABLE).select_related("warehouse")
            warehouse_id = _int(context.get("warehouse_id"))
            if warehouse_id:
                values = values.filter(warehouse_id=warehouse_id)
            if query:
                values = values.filter(Q(code__icontains=query) | Q(name__icontains=query) | Q(warehouse__name__icontains=query))
            return [AutocompleteOption(value=row.pk, label=row.code, secondary=f"{row.warehouse.name} · {row.name}") for row in values.order_by("warehouse__name", "sort_order", "code", "pk")[:limit]]
        if self.entity == "item":
            values = WarehouseItem.objects.filter(pk__in=balances.values("item_id"), is_active=True).select_related("unit")
            if query:
                values = values.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(short_name__icontains=query))
            return [AutocompleteOption(value=row.pk, label=row.name, secondary=f"{row.code} · {row.unit}") for row in values.order_by("name", "code", "pk")[:limit]]
        if self.entity == "category":
            values = WarehouseItemCategory.objects.filter(pk__in=balances.values("item__category_id"), is_active=True)
            if query:
                values = values.filter(Q(name__icontains=query) | Q(code__icontains=query))
            return [AutocompleteOption(value=row.pk, label=row.name, secondary=row.code) for row in values.order_by("name", "code", "pk")[:limit]]
        values = FundingSource.objects.filter(pk__in=balances.values("funding_source_id"), is_active=True)
        if query:
            values = values.filter(Q(name__icontains=query) | Q(code__icontains=query))
        return [AutocompleteOption(value=row.pk, label=row.name, secondary=row.code) for row in values.order_by("name", "code", "pk")[:limit]]


@dataclass(frozen=True)
class WarehouseRelationProvider:
    code: str
    relation: str
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("warehouse_id",)
    result_limit: int = 20

    def can_use(self, user):
        return department_ids_for_warehouse_scope(user, WAREHOUSE_MANAGE_LOCATIONS_SCOPE) != set()

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        if self.relation == "warehouse":
            values = manageable_location_warehouses_queryset(user)
            if query:
                values = values.filter(Q(name__icontains=query) | Q(code__icontains=query))
            return [AutocompleteOption(value=row.pk, label=row.name, secondary=row.code) for row in values.order_by("name", "code", "pk")[:limit]]
        warehouse_id = _int(context.get("warehouse_id"))
        if not warehouse_id:
            return []
        allowed = manageable_location_warehouses_queryset(user).filter(pk=warehouse_id)
        locations = StorageLocation.objects.filter(warehouse__in=allowed, is_active=True, purpose=StorageLocation.Purpose.AVAILABLE)
        if query:
            locations = locations.filter(Q(code__icontains=query) | Q(name__icontains=query))
        return [AutocompleteOption(value=row.pk, label=row.code, secondary=row.name) for row in locations.order_by("sort_order", "code", "pk")[:limit]]


@dataclass(frozen=True)
class WarehouseCatalogRelationProvider:
    code: str
    relation: str
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user):
        from .policies import can_manage_warehouse_catalog
        return can_manage_warehouse_catalog(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        model = WarehouseItemCategory if self.relation == "category" else UnitOfMeasure
        values = model.objects.filter(is_active=True)
        if query:
            values = values.filter(Q(name__icontains=query) | Q(code__icontains=query))
        return [AutocompleteOption(value=row.pk, label=row.name, secondary=row.code) for row in values.order_by("name", "code", "pk")[:limit]]


def register() -> None:
    providers = [
        WarehouseDepartmentProvider(), WarehouseItemProvider(), WarehouseSeriesProvider(), WarehouseSourceProvider(), WarehouseLocationProvider(),
        WarehouseScopedDepartmentProvider("warehouse.report_department", WAREHOUSE_VIEW_SCOPE),
        WarehouseScopedDepartmentProvider("warehouse.stock_department", WAREHOUSE_VIEW_SCOPE),
        WarehouseScopedDepartmentProvider("warehouse.report_profile_department", WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE),
        WarehouseScopedDepartmentProvider("warehouse.manage_department", WAREHOUSE_MANAGE_LOCATIONS_SCOPE),
        WarehouseFilterEntityProvider("warehouse.stock_warehouse", "warehouse"),
        WarehouseFilterEntityProvider("warehouse.stock_location", "location"),
        WarehouseFilterEntityProvider("warehouse.stock_item", "item"),
        WarehouseFilterEntityProvider("warehouse.stock_category", "category"),
        WarehouseFilterEntityProvider("warehouse.stock_source", "source"),
        WarehouseRelationProvider("warehouse.manage_warehouse", "warehouse"),
        WarehouseRelationProvider("warehouse.manage_location", "location"),
        WarehouseCatalogRelationProvider("warehouse.catalog_category", "category"),
        WarehouseCatalogRelationProvider("warehouse.catalog_unit", "unit"),
    ]
    for provider in providers:
        register_autocomplete_provider(provider, replace=True)
