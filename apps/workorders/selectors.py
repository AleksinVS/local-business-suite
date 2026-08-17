from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.core.models import Department

from .department_filter import (
    resolve_department_device_selection,
    resolve_department_selection,
)
from .models import Board, WorkOrder
from .policies import (
    DEFAULT_BOARD_VISIBILITY_GROUP,
    allowed_view_scopes,
    default_board_access_applies,
    user_department_branch_ids,
)


# ``view_scope`` is the kanban capability, but the same effective relation is
# used by the read-only department/device directories.  Keep this vocabulary
# local to selectors: no new capability or role is introduced by the adapters.
_RELATIONAL_VIEW_SCOPES = frozenset(
    {
        "relational",
        "visible",
        "authored",
        "assigned",
        "assigned_or_unassigned",
        "assigned_or_unassigned_or_authored",
    }
)


def resolve_active_actor(user, *, force_refresh=False):
    """Resolve one persisted active actor for a selector operation.

    A marked snapshot is safe only inside the operation that created it.  All
    public selector boundaries force a fresh database read so deactivation,
    department changes and group revocation cannot be hidden by a stale
    request user object.
    """
    if not force_refresh and getattr(user, "_workorders_actor_snapshot", False):
        return user if getattr(user, "is_active", False) else None
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return None
    actor = (
        get_user_model().objects.filter(pk=user.pk, is_active=True)
        .select_related("department")
        .prefetch_related("groups")
        .first()
    )
    if actor is not None:
        actor._workorders_actor_snapshot = True
    return actor


def _active_authenticated(user):
    return resolve_active_actor(user, force_refresh=True)


def _is_actor_snapshot(actor):
    return bool(
        getattr(actor, "_workorders_actor_snapshot", False)
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "pk", None)
    )


def _resource_visibility_mode_for_actor(actor):
    if not _is_actor_snapshot(actor):
        return "none"
    scopes = allowed_view_scopes(actor)
    if "all" in scopes:
        return "all"
    if "department_branch" in scopes:
        return "branch"
    if scopes & _RELATIONAL_VIEW_SCOPES:
        return "relational"
    return "none"


def resource_visibility_mode(user):
    """Return the canonical read scope for related resources.

    ``all`` and ``department_branch`` are explicit broad/branch scopes.  The
    remaining workorder scopes are relation-based: directories may expose only
    departments/devices reached through the actor's visible workorders.  A
    missing/``none`` scope is fail-closed.
    """

    return _resource_visibility_mode_for_actor(_active_authenticated(user))


def _visible_boards_queryset_for_actor(actor):
    if not _is_actor_snapshot(actor):
        return Board.objects.none()
    if actor.is_superuser:
        return Board.objects.all()
    if default_board_access_applies(actor):
        return Board.objects.filter(
            allowed_groups__name=DEFAULT_BOARD_VISIBILITY_GROUP
        ).distinct()
    return Board.objects.filter(allowed_groups__in=actor.groups.all()).distinct()


def visible_boards_queryset(user):
    return _visible_boards_queryset_for_actor(_active_authenticated(user))


def _visible_workorders_queryset_for_actor(actor, board=None):
    if not _is_actor_snapshot(actor):
        return WorkOrder.objects.none()
    queryset = WorkOrder.objects.select_related(
        "board",
        "device",
        "device__department",
        "author",
        "assignee",
        "department",
        "department__parent",
    )

    # A board argument is only an additional narrowing predicate.  It must
    # never replace the actor's board ACL (including for direct selector calls).
    queryset = queryset.filter(board__in=_visible_boards_queryset_for_actor(actor))
    if board is not None:
        queryset = queryset.filter(board=board)

    scopes = allowed_view_scopes(actor)
    if "all" in scopes:
        return queryset
    visibility_filter = Q(pk__in=[])
    if "authored" in scopes:
        visibility_filter |= Q(author=actor)
    if "assigned" in scopes:
        visibility_filter |= Q(assignee=actor)
    if "assigned_or_unassigned" in scopes:
        visibility_filter |= Q(assignee=actor) | Q(assignee__isnull=True)
    if "assigned_or_unassigned_or_authored" in scopes:
        visibility_filter |= Q(assignee=actor) | Q(assignee__isnull=True) | Q(author=actor)
    if "visible" in scopes:
        visibility_filter |= Q(author=actor) | Q(assignee=actor)
    if "department_branch" in scopes:
        branch_ids = user_department_branch_ids(actor)
        if branch_ids:
            visibility_filter |= Q(department_id__in=branch_ids)
    return queryset.filter(visibility_filter).distinct()


def visible_workorders_queryset(user, board=None):
    return _visible_workorders_queryset_for_actor(_active_authenticated(user), board=board)


def _visible_departments_queryset_for_actor(user):
    queryset = Department.objects.select_related("parent").order_by(
        "parent_id", "name", "id"
    )
    mode = _resource_visibility_mode_for_actor(user)
    if mode == "none":
        return queryset.none()
    if mode == "branch":
        branch_ids = user_department_branch_ids(user)
        if not branch_ids:
            return queryset.none()
        queryset = queryset.filter(pk__in=branch_ids)
    elif mode == "relational":
        visible_department_ids = _visible_workorders_queryset_for_actor(user).order_by().values(
            "department_id"
        )
        queryset = queryset.filter(pk__in=visible_department_ids)
    return queryset


def visible_departments_queryset(user):
    return _visible_departments_queryset_for_actor(_active_authenticated(user))


def _creation_departments_queryset_for_actor(user):
    """Departments allowed for a new workorder.

    Creation is deliberately separate from the read directory: a relational
    viewer may see only departments referenced by visible workorders, while a
    creator is still limited to the actor's own organizational branch.
    """

    queryset = Department.objects.select_related("parent").order_by(
        "parent_id", "name", "id"
    )
    mode = _resource_visibility_mode_for_actor(user)
    if mode == "none":
        return queryset.none()
    if mode in {"branch", "relational"}:
        branch_ids = user_department_branch_ids(user)
        if not branch_ids:
            return queryset.none()
        return queryset.filter(pk__in=branch_ids)
    return queryset


def creation_departments_queryset(user):
    return _creation_departments_queryset_for_actor(_active_authenticated(user))


def resolve_visible_department_selection(user, raw_values):
    """Нормализует фильтр строго внутри доступного пользователю дерева."""

    return resolve_department_selection(
        raw_values,
        visible_departments_queryset(user),
    )


def visible_devices_queryset(user, include_archived_ids=()):
    """Адаптер к каноническому селектору инвентаря."""

    from apps.inventory.selectors import visible_devices_queryset as _visible_devices

    return _visible_devices(user, include_archived_ids=include_archived_ids)


def creation_devices_queryset(user):
    """Active devices selectable when creating a workorder."""

    from apps.inventory.selectors import creation_devices_queryset as _creation_devices

    return _creation_devices(user)


def resolve_visible_department_device_selection(
    user,
    raw_department_values,
    raw_device_values,
):
    """Строит выбор дерева только из доступных активных объектов."""

    actor = _active_authenticated(user)
    return _resolve_visible_department_device_selection_for_actor(
        actor,
        raw_department_values,
        raw_device_values,
    )


def _resolve_visible_department_device_selection_for_actor(
    actor,
    raw_department_values,
    raw_device_values,
):
    """Resolve both trees from one marked actor snapshot."""

    from apps.inventory.selectors import _visible_devices_queryset_for_actor

    return resolve_department_device_selection(
        raw_department_values,
        raw_device_values,
        _visible_departments_queryset_for_actor(actor),
        _visible_devices_queryset_for_actor(actor),
    )
