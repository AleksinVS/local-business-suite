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

ROLE_TRANSITIONS = {
    ROLE_CUSTOMER: {WorkOrderStatus.CANCELLED, WorkOrderStatus.CLOSED},
    ROLE_TECHNICIAN: {
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.RESOLVED,
    },
    ROLE_MANAGER: {choice for choice, _label in WorkOrderStatus.choices},
}


def user_roles(user):
    if not user.is_authenticated:
        return set()
    return set(user.groups.values_list("name", flat=True))


def can_manage_inventory(user):
    return user.is_superuser or ROLE_MANAGER in user_roles(user)


def can_edit(user, workorder: WorkOrder) -> bool:
    roles = user_roles(user)
    return user.is_superuser or ROLE_MANAGER in roles or workorder.author_id == user.id


def can_transition(user, workorder: WorkOrder, target_status: str) -> bool:
    roles = user_roles(user)
    if user.is_superuser:
        return target_status in STATUS_TRANSITIONS.get(workorder.status, set())
    if target_status == WorkOrderStatus.CLOSED:
        return can_confirm_closure(user, workorder)
    return (
        target_status in STATUS_TRANSITIONS.get(workorder.status, set())
        and any(target_status in ROLE_TRANSITIONS.get(role, set()) for role in roles)
    )


def can_comment(user) -> bool:
    return user.is_authenticated


def can_confirm_closure(user, workorder: WorkOrder) -> bool:
    roles = user_roles(user)
    if workorder.status != WorkOrderStatus.RESOLVED:
        return False
    return user.is_superuser or ROLE_MANAGER in roles or workorder.author_id == user.id


def can_rate(user, workorder: WorkOrder) -> bool:
    if workorder.status != WorkOrderStatus.CLOSED:
        return False
    return user.is_superuser or workorder.author_id == user.id or ROLE_MANAGER in user_roles(user)
