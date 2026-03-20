from django.db.models import Q

from .models import WorkOrder
from .policies import allowed_view_scopes


def visible_workorders_queryset(user):
    queryset = WorkOrder.objects.select_related("device", "author", "assignee", "department", "department__parent")
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
