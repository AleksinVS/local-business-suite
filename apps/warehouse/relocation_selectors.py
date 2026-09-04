"""Scoped selectors used by the stock-list relocation workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping
from urllib.parse import urlencode

from django.core.paginator import Page, Paginator
from django.db.models import Q, QuerySet

from apps.core.autocomplete import AutocompleteOption, register_autocomplete_provider
from apps.core.models import Department

from .models import (
    FundingSource,
    StockBalance,
    StorageLocation,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
)
from .policies import WAREHOUSE_OPERATE_SCOPE, department_ids_for_warehouse_scope
from .selectors import operable_warehouses_queryset, visible_stock_balances_queryset


STOCK_PAGE_SIZE = 50
STOCK_FILTER_KEYS = (
    "department_id",
    "warehouse_id",
    "location_id",
    "category_id",
    "funding_source_id",
    "item_id",
    "item",
    "series",
    "expires_from",
    "expires_to",
)


def operable_stock_balances_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    """All balance projections in operate scope, including a zeroed replay row."""

    queryset = queryset if queryset is not None else StockBalance.objects.all()
    department_ids = department_ids_for_warehouse_scope(actor, WAREHOUSE_OPERATE_SCOPE)
    if department_ids is None:
        return queryset
    if not department_ids:
        return queryset.none()
    return queryset.filter(department_id__in=department_ids)


def relocatable_stock_balances_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    """Return positive, operational balances inside the actor's operate scope."""

    queryset = operable_stock_balances_queryset(actor, queryset=queryset)
    return queryset.filter(
        quantity__gt=0,
        warehouse__is_active=True,
        location__is_active=True,
        location__purpose=StorageLocation.Purpose.AVAILABLE,
        item__is_active=True,
        item__unit__is_active=True,
        funding_source__is_active=True,
    )


def visible_relocatable_stock_balances_queryset(
    actor, *, queryset: QuerySet | None = None
) -> QuerySet:
    """Positive available balances visible for read-only stock browsing."""

    queryset = visible_stock_balances_queryset(actor, queryset=queryset)
    return queryset.filter(
        quantity__gt=0,
        warehouse__is_active=True,
        location__is_active=True,
        location__purpose=StorageLocation.Purpose.AVAILABLE,
        item__is_active=True,
        item__unit__is_active=True,
        funding_source__is_active=True,
    )


def filtered_relocatable_stock_balances_queryset(actor, params: Mapping[str, str]) -> QuerySet:
    queryset = relocatable_stock_balances_queryset(actor).select_related(
        "department",
        "warehouse",
        "location",
        "item__unit",
        "item__category",
        "funding_source",
    )
    return _filter_stock_balances(queryset, params)


def _filter_stock_balances(queryset: QuerySet, params: Mapping[str, str]) -> QuerySet:
    integer_filters = {
        "department_id": "department_id",
        "warehouse_id": "warehouse_id",
        "location_id": "location_id",
        "item_id": "item_id",
        "category_id": "item__category_id",
        "funding_source_id": "funding_source_id",
    }
    for parameter, lookup in integer_filters.items():
        value = _positive_int(params.get(parameter))
        if value is not None:
            queryset = queryset.filter(**{lookup: value})

    item_query = str(params.get("item", "") or "").strip()[:100]
    if item_query:
        queryset = queryset.filter(
            Q(item__name__icontains=item_query) | Q(item__code__icontains=item_query)
        )
    series = str(params.get("series", "") or "").strip()[:100]
    if series:
        queryset = queryset.filter(series__icontains=series)
    expires_from = _iso_date(params.get("expires_from"))
    if expires_from:
        queryset = queryset.filter(expires_on__gte=expires_from)
    expires_to = _iso_date(params.get("expires_to"))
    if expires_to:
        queryset = queryset.filter(expires_on__lte=expires_to)
    return queryset.order_by(
        "department__name",
        "warehouse__name",
        "location__sort_order",
        "location__code",
        "item__name",
        "expires_on",
        "series_key",
        "funding_source__name",
        "pk",
    )


def filtered_visible_stock_balances_queryset(actor, params: Mapping[str, str]) -> QuerySet:
    """Read-only counterpart; never grants the relocation operate scope."""

    queryset = visible_relocatable_stock_balances_queryset(actor).select_related(
        "department", "warehouse", "location", "item__unit", "item__category", "funding_source"
    )
    return _filter_stock_balances(queryset, params)


def paginated_relocatable_stock_balances(
    actor, params: Mapping[str, str], *, page_size: int = STOCK_PAGE_SIZE
) -> Page:
    page_size = max(1, min(int(page_size), 200))
    return Paginator(
        filtered_relocatable_stock_balances_queryset(actor, params), page_size
    ).get_page(params.get("page") or 1)


def paginated_visible_stock_balances(
    actor, params: Mapping[str, str], *, page_size: int = STOCK_PAGE_SIZE
) -> Page:
    page_size = max(1, min(int(page_size), 200))
    return Paginator(
        filtered_visible_stock_balances_queryset(actor, params), page_size
    ).get_page(params.get("page") or 1)


def stock_filter_options(actor, params: Mapping[str, str], *, operate: bool = True) -> dict:
    """Return only values represented by balances in the requested read scope."""

    base = (
        relocatable_stock_balances_queryset(actor)
        if operate
        else visible_relocatable_stock_balances_queryset(actor)
    )
    department_ids = base.values_list("department_id", flat=True).distinct()
    warehouse_base = base
    department_id = _positive_int(params.get("department_id"))
    if department_id is not None:
        warehouse_base = warehouse_base.filter(department_id=department_id)
    warehouse_ids = warehouse_base.values_list("warehouse_id", flat=True).distinct()

    location_base = warehouse_base
    warehouse_id = _positive_int(params.get("warehouse_id"))
    if warehouse_id is not None:
        location_base = location_base.filter(warehouse_id=warehouse_id)
    location_ids = location_base.values_list("location_id", flat=True).distinct()

    return {
        "departments": Department.objects.filter(pk__in=department_ids).order_by(
            "name", "pk"
        ),
        "warehouses": Warehouse.objects.filter(pk__in=warehouse_ids).order_by(
            "name", "code", "pk"
        ),
        "locations": StorageLocation.objects.filter(pk__in=location_ids).order_by(
            "warehouse__name", "sort_order", "code", "pk"
        ),
        "categories": WarehouseItemCategory.objects.filter(
            pk__in=base.values_list("item__category_id", flat=True).distinct()
        ).order_by("name", "code", "pk"),
        "items": WarehouseItem.objects.filter(
            pk__in=base.values_list("item_id", flat=True).distinct()
        ).order_by("name", "code", "pk"),
        "funding_sources": FundingSource.objects.filter(
            pk__in=base.values_list("funding_source_id", flat=True).distinct()
        ).order_by("name", "code", "pk"),
        "item_suggestions": tuple(
            base.order_by("item__name")
            .values_list("item__name", flat=True)
            .distinct()[:50]
        ),
        "series_suggestions": tuple(
            base.exclude(series="")
            .order_by("series")
            .values_list("series", flat=True)
            .distinct()[:50]
        ),
    }


def sanitized_stock_filter_query(params: Mapping[str, str]) -> str:
    """Build a bounded pagination query without unknown keys or duplicate page."""

    sanitized = []
    for key in STOCK_FILTER_KEYS[:7]:
        value = _positive_int(params.get(key))
        if value is not None:
            sanitized.append((key, str(value)))
    if _positive_int(params.get("item_id")) is None:
        value = str(params.get("item", "") or "").strip()[:100]
        if value:
            sanitized.append(("item", value))
    for key in ("series",):
        value = str(params.get(key, "") or "").strip()[:100]
        if value:
            sanitized.append((key, value))
    for key in ("expires_from", "expires_to"):
        value = _iso_date(params.get(key))
        if value:
            sanitized.append((key, value.isoformat()))
    return urlencode(sanitized)


def relocation_destination_warehouses_queryset(actor, *, department_id: int) -> QuerySet:
    return (
        operable_warehouses_queryset(actor)
        .filter(
            department_id=department_id,
            is_active=True,
            locations__is_active=True,
            locations__purpose=StorageLocation.Purpose.AVAILABLE,
        )
        .distinct()
        .order_by("name", "code", "pk")
    )


def relocation_destination_locations_queryset(
    actor, *, department_id: int, warehouse_id: int
) -> QuerySet:
    allowed_warehouses = relocation_destination_warehouses_queryset(
        actor, department_id=department_id
    ).filter(pk=warehouse_id)
    return StorageLocation.objects.filter(
        warehouse__in=allowed_warehouses,
        is_active=True,
        purpose=StorageLocation.Purpose.AVAILABLE,
    ).order_by("sort_order", "code", "pk")


@dataclass(frozen=True)
class RelocationDestinationAutocompleteProvider:
    code: str = "warehouse.relocation_destination"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department",)
    result_limit: int = 20

    def can_use(self, user) -> bool:
        return department_ids_for_warehouse_scope(user, WAREHOUSE_OPERATE_SCOPE) != set()

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        department_id = _positive_int(context.get("department"))
        if department_id is None:
            return []
        queryset = relocation_destination_warehouses_queryset(
            user, department_id=department_id
        ).select_related("default_receiving_location", "department")
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(code__icontains=query))
        options = []
        for warehouse in queryset[:limit]:
            default = warehouse.default_receiving_location
            default_is_valid = bool(
                default
                and default.warehouse_id == warehouse.pk
                and default.is_active
                and default.purpose == StorageLocation.Purpose.AVAILABLE
            )
            options.append(
                AutocompleteOption(
                    value=warehouse.pk,
                    label=warehouse.name,
                    secondary=f"{warehouse.department.name} · {warehouse.code}",
                    metadata={
                        "department_id": warehouse.department_id,
                        "default_location_id": default.pk if default_is_valid else None,
                        "default_location_label": str(default) if default_is_valid else "",
                    },
                )
            )
        return options


@dataclass(frozen=True)
class RelocationLocationAutocompleteProvider:
    code: str = "warehouse.relocation_location"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department", "warehouse")
    result_limit: int = 20

    def can_use(self, user) -> bool:
        return department_ids_for_warehouse_scope(user, WAREHOUSE_OPERATE_SCOPE) != set()

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        department_id = _positive_int(context.get("department"))
        warehouse_id = _positive_int(context.get("warehouse"))
        if department_id is None or warehouse_id is None:
            return []
        queryset = relocation_destination_locations_queryset(
            user,
            department_id=department_id,
            warehouse_id=warehouse_id,
        )
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(code__icontains=query))
        return [
            AutocompleteOption(
                value=location.pk,
                label=f"{location.code} — {location.name}",
                secondary=location.warehouse.name,
                metadata={"warehouse_id": location.warehouse_id},
            )
            for location in queryset.select_related("warehouse")[:limit]
        ]


def register_relocation_autocomplete_providers() -> None:
    register_autocomplete_provider(
        RelocationDestinationAutocompleteProvider(), replace=True
    )
    register_autocomplete_provider(
        RelocationLocationAutocompleteProvider(), replace=True
    )


def _positive_int(value) -> int | None:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _iso_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None
