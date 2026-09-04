"""Inventory-owned providers for the shared autocomplete transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from apps.core.autocomplete import AutocompleteOption, register_autocomplete_provider
from apps.workorders.policies import can_access_inventory
from apps.workorders.selectors import resolve_active_actor

from .selectors import visible_departments_queryset, visible_devices_queryset


@dataclass(frozen=True)
class InventoryDepartmentAutocompleteProvider:
    code: str = "inventory.department"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_access_inventory(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        departments = visible_departments_queryset(user).select_related("parent")
        if query:
            departments = departments.filter(name__icontains=query)
        return [
            AutocompleteOption(
                value=department.pk,
                label=getattr(department, "indented_name", department.name),
                secondary=getattr(department, "full_name", ""),
            )
            for department in departments.order_by("parent_id", "name", "id")[:limit]
        ]


@dataclass(frozen=True)
class InventoryDeviceSuggestionProvider:
    code: str
    field: str
    context_keys: tuple[str, ...] = ()
    mode: str = "suggestion"
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_access_inventory(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        devices = visible_devices_queryset(user)
        department_id = _positive_int(context.get("department"))
        if department_id:
            devices = devices.filter(department_id=department_id)
        if self.field == "model":
            manufacturer = (context.get("manufacturer") or "").strip()
            if manufacturer:
                devices = devices.filter(manufacturer__iexact=manufacturer)
        lookup = f"{self.field}__icontains"
        if query:
            devices = devices.filter(**{lookup: query})
        values = (
            devices.exclude(**{self.field: ""})
            .exclude(**{f"{self.field}__isnull": True})
            .values_list(self.field, flat=True)
            .order_by(self.field)
            .distinct()
        )
        seen = set()
        options = []
        for value in values[:limit * 2]:
            text = str(value).strip()
            if not text or text.casefold() in seen:
                continue
            seen.add(text.casefold())
            options.append(AutocompleteOption(value=text, label=text))
            if len(options) >= limit:
                break
        return options


def register() -> None:
    register_autocomplete_provider(
        InventoryDepartmentAutocompleteProvider(), replace=True
    )
    for code, field, context in (
        ("inventory.device_name", "name", ()),
        ("inventory.manufacturer", "manufacturer", ()),
        ("inventory.production_country", "production_country", ()),
        ("inventory.model", "model", ("manufacturer",)),
        ("inventory.address", "address", ("department",)),
        ("inventory.location", "location", ("department",)),
    ):
        register_autocomplete_provider(
            InventoryDeviceSuggestionProvider(code=code, field=field, context_keys=context),
            replace=True,
        )


def _positive_int(value: str | None) -> int | None:
    try:
        normalized = int(value or "")
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None
