from .models import WorkOrder, WorkOrderStatus

ROLE_CUSTOMER = "customer"
ROLE_TECHNICIAN = "technician"
ROLE_MANAGER = "manager"

STATUS_TRANSITIONS = {
    WorkOrderStatus.NEW: {WorkOrderStatus.ACCEPTED, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.ACCEPTED: {
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.IN_PROGRESS: {
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.RESOLVED,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.ON_HOLD: {
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.RESOLVED: {WorkOrderStatus.CLOSED, WorkOrderStatus.IN_PROGRESS},
    WorkOrderStatus.CLOSED: set(),
    WorkOrderStatus.CANCELLED: set(),
}

TECHNICIAN_TRANSITIONS = {
    WorkOrderStatus.ACCEPTED,
    WorkOrderStatus.IN_PROGRESS,
    WorkOrderStatus.ON_HOLD,
    WorkOrderStatus.RESOLVED,
}


def user_roles(user):
    if not user.is_authenticated:
        return set()
    return set(user.groups.values_list("name", flat=True))


def is_manager(user):
    return user.is_superuser or ROLE_MANAGER in user_roles(user)


def is_customer(user):
    return user.is_authenticated and (user.is_superuser or ROLE_CUSTOMER in user_roles(user))


def is_technician(user):
    return user.is_authenticated and (user.is_superuser or ROLE_TECHNICIAN in user_roles(user))


def can_manage_inventory(user):
    return is_manager(user)


def can_view(user, workorder: WorkOrder) -> bool:
    if not user.is_authenticated:
        return False
    if is_manager(user) or is_customer(user):
        return True
    if is_technician(user):
        return workorder.assignee_id in {None, user.id} or workorder.author_id == user.id
    return False


def can_create(user) -> bool:
    return user.is_authenticated and (is_customer(user) or is_manager(user))


def can_edit(user, workorder: WorkOrder) -> bool:
    if not can_view(user, workorder):
        return False
    return is_manager(user) or workorder.author_id == user.id


def can_assign(user, workorder: WorkOrder) -> bool:
    return is_manager(user) and can_view(user, workorder)


def can_comment(user, workorder: WorkOrder) -> bool:
    return can_view(user, workorder)


def can_upload_attachment(user, workorder: WorkOrder) -> bool:
    return is_manager(user) or is_technician(user) or workorder.author_id == user.id


def can_confirm_closure(user, workorder: WorkOrder) -> bool:
    if workorder.status != WorkOrderStatus.RESOLVED:
        return False
    return is_manager(user) or workorder.author_id == user.id


def can_rate(user, workorder: WorkOrder) -> bool:
    if workorder.status != WorkOrderStatus.CLOSED:
        return False
    return is_manager(user) or workorder.author_id == user.id


def can_transition(user, workorder: WorkOrder, target_status: str) -> bool:
    if not can_view(user, workorder):
        return False
    allowed = STATUS_TRANSITIONS.get(workorder.status, set())
    if target_status not in allowed:
        return False
    if user.is_superuser or is_manager(user):
        return True
    if target_status == WorkOrderStatus.CLOSED:
        return can_confirm_closure(user, workorder)
    if is_customer(user):
        return target_status == WorkOrderStatus.CANCELLED and workorder.author_id == user.id
    if is_technician(user):
        return target_status in TECHNICIAN_TRANSITIONS
    return False
