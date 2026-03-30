from django.utils import timezone

from .models import WorkOrder, WorkOrderStatus, WorkOrderTransitionLog


def create_workorder(*, author, title: str, description: str, department, priority, device_id=None, assignee=None) -> WorkOrder:
    return WorkOrder.objects.create(
        author=author,
        title=title,
        description=description,
        department=department,
        priority=priority,
        device_id=device_id,
        assignee=assignee,
    )


def transition_workorder(*, workorder: WorkOrder, user, to_status: str) -> WorkOrder:
    previous_status = workorder.status
    workorder.status = to_status
    if to_status != WorkOrderStatus.CLOSED:
        workorder.closure_confirmed = False
        workorder.closure_confirmed_at = None
    workorder.save(
        update_fields=[
            "status",
            "updated_at",
            "resolved_at",
            "closed_at",
            "closure_confirmed",
            "closure_confirmed_at",
        ]
    )
    WorkOrderTransitionLog.objects.create(
        workorder=workorder,
        from_status=previous_status,
        to_status=to_status,
        actor=user,
    )
    return workorder


def confirm_closure(*, workorder: WorkOrder, user) -> WorkOrder:
    previous_status = workorder.status
    workorder.status = WorkOrderStatus.CLOSED
    workorder.closure_confirmed = True
    workorder.closure_confirmed_at = timezone.now()
    workorder.save(
        update_fields=[
            "status",
            "updated_at",
            "closed_at",
            "closure_confirmed",
            "closure_confirmed_at",
        ]
    )
    WorkOrderTransitionLog.objects.create(
        workorder=workorder,
        from_status=previous_status,
        to_status=WorkOrderStatus.CLOSED,
        actor=user,
    )
    return workorder


def rate_workorder(*, workorder: WorkOrder, user, rating: int) -> WorkOrder:
    workorder.rating = rating
    workorder.save(update_fields=["rating"])
    return workorder
