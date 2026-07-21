from django.db.models import Q

from apps.core.models import Department
from apps.inventory.models import MedicalDevice

from .models import Board, WorkOrder
from .policies import allowed_view_scopes, user_department_branch_ids


def visible_boards_queryset(user):
    if not user.is_authenticated:
        return Board.objects.none()
    if user.is_superuser:
        return Board.objects.all()
    return Board.objects.filter(allowed_groups__in=user.groups.all()).distinct()


def visible_workorders_queryset(user, board=None):
    queryset = WorkOrder.objects.select_related(
        "board",
        "device",
        "device__department",
        "author",
        "assignee",
        "department",
        "department__parent",
    )
    
    # Filter by board if provided, otherwise filter by visible boards
    if board:
        queryset = queryset.filter(board=board)
    else:
        queryset = queryset.filter(board__in=visible_boards_queryset(user))

    scopes = allowed_view_scopes(user)
    if "all" in scopes:
        return queryset
    visibility_filter = Q(pk__in=[])
    if "authored" in scopes:
        visibility_filter |= Q(author=user)
    if "assigned" in scopes:
        visibility_filter |= Q(assignee=user)
    if "assigned_or_unassigned" in scopes:
        visibility_filter |= Q(assignee=user) | Q(assignee__isnull=True)
    if "assigned_or_unassigned_or_authored" in scopes:
        visibility_filter |= Q(assignee=user) | Q(assignee__isnull=True) | Q(author=user)
    if "visible" in scopes:
        visibility_filter |= Q(author=user) | Q(assignee=user)
    if "department_branch" in scopes:
        branch_ids = user_department_branch_ids(user)
        if branch_ids:
            visibility_filter |= Q(department_id__in=branch_ids)
    return queryset.filter(visibility_filter).distinct()


def _is_department_branch_limited(user):
    scopes = allowed_view_scopes(user)
    return "department_branch" in scopes and "all" not in scopes


def visible_departments_queryset(user):
    queryset = Department.objects.select_related("parent").order_by(
        "parent_id", "name", "id"
    )
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if _is_department_branch_limited(user):
        branch_ids = user_department_branch_ids(user)
        if not branch_ids:
            return queryset.none()
        queryset = queryset.filter(pk__in=branch_ids)
    return queryset


def visible_devices_queryset(user):
    queryset = MedicalDevice.objects.select_related("department").order_by("name")
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if _is_department_branch_limited(user):
        branch_ids = user_department_branch_ids(user)
        if not branch_ids:
            return queryset.none()
        queryset = queryset.filter(department_id__in=branch_ids)
    return queryset
