from django.utils import timezone

from .models import WorkOrder, WorkOrderStatus, WorkOrderTransitionLog


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
