"""Actor-aware read selectors for medical devices.

The workorders selector owns the effective actor scope because device
visibility may be relational to visible workorders.  This module is the
inventory-facing adapter used by inventory HTTP and AI read paths.
"""

from django.db.models import Q

from .models import MedicalDevice


def visible_departments_queryset(user):
    """Return departments visible in the workorders resource scope."""

    from apps.workorders.selectors import visible_departments_queryset as _visible

    return _visible(user)


def creation_departments_queryset(user):
    """Return departments allowed as a target for a new inventory item."""

    from apps.workorders.selectors import creation_departments_queryset as _creation

    return _creation(user)


def _visible_devices_queryset_for_actor(
    actor,
    *,
    include_archived=False,
    include_archived_ids=(),
):
    """Return devices in the actor's canonical resource scope.

    ``include_archived_ids`` is only for preserving an existing relation (for
    example, an archived device on an editable workorder).  It is applied after
    scope filtering, so a foreign archived id can never widen visibility.
    """

    queryset = MedicalDevice.objects.select_related("department").order_by(
        "department_id", "name", "inventory_number", "id"
    )

    from apps.workorders.selectors import (
        _is_actor_snapshot,
        _resource_visibility_mode_for_actor,
        _visible_workorders_queryset_for_actor,
        user_department_branch_ids,
    )

    if not _is_actor_snapshot(actor):
        return queryset.none()
    mode = _resource_visibility_mode_for_actor(actor)
    if mode == "none":
        return queryset.none()
    if mode == "branch":
        branch_ids = user_department_branch_ids(actor)
        if not branch_ids:
            return queryset.none()
        queryset = queryset.filter(department_id__in=branch_ids)
    elif mode == "relational":
        visible_device_ids = (
            _visible_workorders_queryset_for_actor(actor)
            .filter(device_id__isnull=False)
            .order_by()
            .values("device_id")
        )
        queryset = queryset.filter(pk__in=visible_device_ids)

    preserved_ids = {
        device_id
        for device_id in include_archived_ids
        if isinstance(device_id, int) and device_id > 0
    }
    if include_archived:
        return queryset
    if preserved_ids:
        return queryset.filter(Q(is_archived=False) | Q(pk__in=preserved_ids))
    return queryset.filter(is_archived=False)


def visible_devices_queryset(user, *, include_archived=False, include_archived_ids=()):
    from apps.workorders.selectors import resolve_active_actor

    actor = resolve_active_actor(user, force_refresh=True)
    return _visible_devices_queryset_for_actor(
        actor,
        include_archived=include_archived,
        include_archived_ids=include_archived_ids,
    )


def _creation_devices_queryset_for_actor(actor):
    """Return active devices selectable for a new domain relation."""

    queryset = MedicalDevice.objects.select_related("department").order_by(
        "department_id", "name", "inventory_number", "id"
    )
    from apps.workorders.selectors import _creation_departments_queryset_for_actor

    departments = _creation_departments_queryset_for_actor(actor)
    return queryset.filter(
        department_id__in=departments.order_by().values("pk"),
        is_archived=False,
    )


def creation_devices_queryset(user):
    from apps.workorders.selectors import resolve_active_actor

    return _creation_devices_queryset_for_actor(
        resolve_active_actor(user, force_refresh=True)
    )
