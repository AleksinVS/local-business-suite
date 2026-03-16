from .models import WorkOrder, WorkOrderTransitionLog


def transition_workorder(*, workorder: WorkOrder, user, to_status: str) -> WorkOrder:
    previous_status = workorder.status
    workorder.status = to_status
    workorder.save(update_fields=["status", "updated_at", "resolved_at", "closed_at", "closure_confirmed"])
    WorkOrderTransitionLog.objects.create(
        workorder=workorder,
        from_status=previous_status,
        to_status=to_status,
        actor=user,
    )
    return workorder
