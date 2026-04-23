from django.db.models import Q

from .models import Board, WorkOrder
from .policies import allowed_view_scopes


def visible_boards_queryset(user):
    if not user.is_authenticated:
        return Board.objects.none()
    if user.is_superuser:
        return Board.objects.all()
    return Board.objects.filter(allowed_groups__in=user.groups.all()).distinct()


def visible_workorders_queryset(user, board=None):
    queryset = WorkOrder.objects.select_related("board", "device", "author", "assignee", "department", "department__parent")
    
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
    return queryset.filter(visibility_filter).distinct()
