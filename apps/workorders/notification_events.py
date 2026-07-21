from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.notifications.models import NotificationSeverity
from apps.notifications.services import create_notification_event

from .models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from .policies import can_view

User = get_user_model()

EVENT_CREATED = "workorders.created"
EVENT_UPDATED = "workorders.updated"
EVENT_ASSIGNED = "workorders.assigned"
EVENT_COMMENT_CREATED = "workorders.comment_created"
EVENT_STATUS_CHANGED = "workorders.status_changed"
EVENT_CLOSED = "workorders.closed"


def _workorder_url(workorder: WorkOrder) -> str:
    return reverse("workorders:detail", args=[workorder.pk])


def _visible_recipients(workorder: WorkOrder, *, exclude_user=None):
    excluded_id = getattr(exclude_user, "pk", None)
    users = User.objects.filter(is_active=True).select_related("department").prefetch_related("groups")
    recipients = []
    for user in users:
        if excluded_id and user.pk == excluded_id:
            continue
        if can_view(user, workorder):
            recipients.append(user)
    return recipients


def _severity_for_workorder(workorder: WorkOrder) -> str:
    if workorder.priority == WorkOrderPriority.CRITICAL:
        return NotificationSeverity.CRITICAL
    if workorder.priority == WorkOrderPriority.HIGH:
        return NotificationSeverity.WARNING
    return NotificationSeverity.INFO


def _status_label(status: str) -> str:
    return dict(WorkOrderStatus.choices).get(status, status)


def _emit(
    *,
    workorder: WorkOrder,
    event_type: str,
    title: str,
    recipients,
    severity: str | None = None,
    metadata: dict | None = None,
):
    return create_notification_event(
        event_type=event_type,
        source_app="workorders",
        source_object_type="workorder",
        source_object_id=workorder.pk,
        title=title,
        body="Открыть в портале",
        target_url=_workorder_url(workorder),
        severity=severity or _severity_for_workorder(workorder),
        recipients=recipients,
        metadata=metadata or {},
    )


def notify_workorder_created(workorder: WorkOrder, *, actor):
    return _emit(
        workorder=workorder,
        event_type=EVENT_CREATED,
        title=f"Новая заявка №{workorder.number}",
        recipients=_visible_recipients(workorder, exclude_user=actor),
        metadata={"actor_id": getattr(actor, "pk", None)},
    )


def notify_workorder_updated(
    workorder: WorkOrder,
    *,
    actor,
    changed_fields: set[str] | None = None,
    previous_assignee_id=None,
):
    changed_fields = changed_fields or set()
    if "assignee" in changed_fields and workorder.assignee_id and workorder.assignee_id != previous_assignee_id:
        assignee = workorder.assignee
        if assignee and assignee != actor and can_view(assignee, workorder):
            _emit(
                workorder=workorder,
                event_type=EVENT_ASSIGNED,
                title=f"Заявка №{workorder.number} назначена вам",
                recipients=[assignee],
                metadata={"actor_id": getattr(actor, "pk", None)},
            )

    recipients = _visible_recipients(workorder, exclude_user=actor)
    if workorder.assignee_id and "assignee" in changed_fields:
        recipients = [user for user in recipients if user.pk != workorder.assignee_id]
    if not recipients:
        return None
    return _emit(
        workorder=workorder,
        event_type=EVENT_UPDATED,
        title=f"Заявка №{workorder.number} изменена",
        recipients=recipients,
        metadata={
            "actor_id": getattr(actor, "pk", None),
            "changed_fields": sorted(changed_fields),
        },
    )


def notify_workorder_comment_created(workorder: WorkOrder, *, actor):
    return _emit(
        workorder=workorder,
        event_type=EVENT_COMMENT_CREATED,
        title=f"Новый комментарий в заявке №{workorder.number}",
        recipients=_visible_recipients(workorder, exclude_user=actor),
        metadata={"actor_id": getattr(actor, "pk", None)},
    )


def notify_workorder_status_changed(workorder: WorkOrder, *, actor, previous_status: str):
    event_type = EVENT_CLOSED if workorder.status == WorkOrderStatus.CLOSED else EVENT_STATUS_CHANGED
    title = (
        f"Заявка №{workorder.number} закрыта"
        if workorder.status == WorkOrderStatus.CLOSED
        else f"Статус заявки №{workorder.number}: {_status_label(workorder.status)}"
    )
    return _emit(
        workorder=workorder,
        event_type=event_type,
        title=title,
        recipients=_visible_recipients(workorder, exclude_user=actor),
        metadata={
            "actor_id": getattr(actor, "pk", None),
            "from_status": previous_status,
            "to_status": workorder.status,
        },
    )
