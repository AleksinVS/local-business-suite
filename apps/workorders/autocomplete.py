from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.core.autocomplete import (
    AutocompleteOption,
    register_autocomplete_provider,
)

from .forms import device_choice_label
from .policies import can_access_workorders, can_create, can_manage_assignments
from .selectors import (
    creation_departments_queryset,
    creation_devices_queryset,
    resolve_active_actor,
    visible_boards_queryset,
    visible_departments_queryset,
    visible_devices_queryset,
)


@dataclass(frozen=True)
class WorkOrderDepartmentAutocompleteProvider:
    code: str = "workorders.department"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_create(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        normalized_query = query.casefold()
        departments = tuple(creation_departments_queryset(user))
        labels = _department_option_labels(departments)
        matches = []
        for department in departments:
            label = labels[department.pk]
            if (
                normalized_query
                and normalized_query not in department.name.casefold()
                and normalized_query not in label.casefold()
            ):
                continue
            matches.append(AutocompleteOption(value=department.pk, label=label))
            if len(matches) >= limit:
                break
        return matches


@dataclass(frozen=True)
class WorkOrderDeviceAutocompleteProvider:
    code: str = "workorders.device"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department",)
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_create(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        devices = creation_devices_queryset(user)
        department_id = _positive_int(context.get("department"))
        if department_id is not None:
            # Filtering the already access-scoped queryset cannot widen access.
            devices = devices.filter(department_id=department_id)
        if query:
            devices = devices.filter(
                Q(name__icontains=query)
                | Q(inventory_number__icontains=query)
                | Q(serial_number__icontains=query)
            )
        devices = list(devices[:limit])
        department_labels = _department_option_labels(
            tuple(creation_departments_queryset(user))
        )
        return [
            AutocompleteOption(
                value=device.pk,
                label=device_choice_label(device),
                secondary=department_labels.get(device.department_id, device.department.name),
                metadata={
                    "name": device.name,
                    "department_id": device.department_id,
                    "department_label": department_labels.get(
                        device.department_id,
                        device.department.name,
                    ),
                },
            )
            for device in devices
        ]


@dataclass(frozen=True)
class WorkOrderUpdateDepartmentAutocompleteProvider:
    code: str = "workorders.update_department"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_access_workorders(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        departments = visible_departments_queryset(user)
        if query:
            departments = departments.filter(name__icontains=query)
        return [
            AutocompleteOption(value=department.pk, label=department_choice_label(department))
            for department in departments.order_by("parent_id", "name", "id")[:limit]
        ]


@dataclass(frozen=True)
class WorkOrderBoardAutocompleteProvider:
    code: str = "workorders.board"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_access_workorders(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        boards = visible_boards_queryset(user)
        if query:
            boards = boards.filter(title__icontains=query)
        return [AutocompleteOption(value=board.pk, label=board.title) for board in boards.order_by("title", "pk")[:limit]]


@dataclass(frozen=True)
class WorkOrderUpdateDeviceAutocompleteProvider:
    code: str = "workorders.update_device"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department", "current_device")
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return actor is not None and can_access_workorders(actor)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        current_device = _positive_int(context.get("current_device"))
        devices = visible_devices_queryset(
            user, include_archived_ids=(current_device,) if current_device else ()
        )
        department_id = _positive_int(context.get("department"))
        if department_id:
            devices = devices.filter(department_id=department_id)
        if query:
            devices = devices.filter(
                Q(name__icontains=query)
                | Q(inventory_number__icontains=query)
                | Q(serial_number__icontains=query)
            )
        return [
            AutocompleteOption(value=device.pk, label=device_choice_label(device))
            for device in devices[:limit]
        ]


@dataclass(frozen=True)
class WorkOrderAssigneeAutocompleteProvider:
    code: str = "workorders.assignee"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("workorder", "current_assignee")
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return (
            actor is not None
            and can_access_workorders(actor)
            and can_manage_assignments(actor)
        )

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        # This mirrors the update form/service boundary: managers may choose
        # any active user.  Visibility of workorders must not accidentally
        # narrow assignment to people who already happen to be assigned.
        users = get_user_model().objects.filter(is_active=True)
        if query:
            users = users.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )
        return [
            AutocompleteOption(
                value=user.pk,
                label=user.get_full_name() or user.username,
                secondary=user.username,
            )
            for user in users.order_by("first_name", "last_name", "username", "pk")[:limit]
        ]


def register() -> None:
    register_autocomplete_provider(
        WorkOrderDepartmentAutocompleteProvider(),
        replace=True,
    )
    register_autocomplete_provider(
        WorkOrderDeviceAutocompleteProvider(),
        replace=True,
    )
    for provider in (
        WorkOrderUpdateDepartmentAutocompleteProvider(),
        WorkOrderBoardAutocompleteProvider(),
        WorkOrderUpdateDeviceAutocompleteProvider(),
        WorkOrderAssigneeAutocompleteProvider(),
    ):
        register_autocomplete_provider(provider, replace=True)


def _positive_int(value: str | None) -> int | None:
    try:
        normalized = int(value or "")
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _department_option_labels(departments) -> dict[int, str]:
    department_by_id = {department.pk: department for department in departments}
    labels: dict[int, str] = {}

    def build_label(department_id: int, visited: tuple[int, ...] = ()) -> str:
        if department_id in labels:
            return labels[department_id]
        department = department_by_id[department_id]
        if department_id in visited or department.parent_id not in department_by_id:
            label = department.name
        else:
            label = f"{build_label(department.parent_id, (*visited, department_id))} / {department.name}"
        labels[department_id] = label
        return label

    for department_id in department_by_id:
        build_label(department_id)
    return labels
