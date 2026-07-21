from apps.core.contract_store import get_contract

from .models import WorkOrder, WorkOrderStatus

ROLE_CUSTOMER = "customer"
ROLE_TECHNICIAN = "technician"
ROLE_MANAGER = "manager"

def user_roles(user):
    if not user.is_authenticated:
        return set()
    return set(user.groups.values_list("name", flat=True))


def role_rules():
    return get_contract("role_rules")


def workflow_rules():
    return get_contract("workflow_rules")


def status_transitions():
    return {
        status: set(targets)
        for status, targets in workflow_rules().get("transitions", {}).items()
    }


def active_role_rules(user):
    if getattr(user, "is_superuser", False):
        return [{"name": "superuser", **superuser_rules()}]
    rules = role_rules()
    return [{"name": role, **rules[role]} for role in user_roles(user) if role in rules]


def superuser_rules():
    return {
        "view_scope": "all",
        "create_workorder": True,
        "edit_scope": "all",
        "comment_scope": "visible",
        "upload_attachment_scope": "visible",
        "confirm_closure_scope": "all",
        "rate_scope": "all",
        "transition_scope": "all",
        "transition_targets": "*",
        "manage_inventory": True,
        "manage_board_columns": True,
        "manage_assignments": True,
        "view_analytics": True,
        "manage_departments": True,
        "manage_roles": True,
        "manage_ai_skills": True,
    }


def has_role_capability(user, capability):
    return any(rule.get(capability) for rule in active_role_rules(user))


def user_department_branch_ids(user):
    if not getattr(user, "is_authenticated", False):
        return set()
    if not getattr(user, "department_id", None):
        return set()
    cache_key = "_workorders_department_branch_ids"
    if not hasattr(user, cache_key):
        setattr(user, cache_key, set(user.department.descendant_ids()))
    return getattr(user, cache_key)


def scope_matches(user, workorder, scope):
    if scope in {None, "none"}:
        return False
    if scope == "all":
        return True
    if scope == "visible":
        return can_view(user, workorder)
    if scope == "authored":
        return workorder.author_id == user.id
    if scope == "assigned":
        return workorder.assignee_id == user.id
    if scope == "assigned_or_unassigned":
        return workorder.assignee_id in {None, user.id}
    if scope == "assigned_or_unassigned_or_authored":
        return workorder.assignee_id in {None, user.id} or workorder.author_id == user.id
    if scope == "department_branch":
        return workorder.department_id in user_department_branch_ids(user)
    return False


def allowed_view_scopes(user):
    return {rule.get("view_scope", "none") for rule in active_role_rules(user)}


def is_manager(user):
    return can_manage_departments(user)


def is_customer(user):
    return ROLE_CUSTOMER in user_roles(user) or getattr(user, "is_superuser", False)


def is_technician(user):
    return ROLE_TECHNICIAN in user_roles(user) or getattr(user, "is_superuser", False)


def can_manage_inventory(user):
    return has_role_capability(user, "manage_inventory")


def can_manage_board_columns(user):
    return has_role_capability(user, "manage_board_columns")


def can_manage_assignments(user):
    return has_role_capability(user, "manage_assignments")


def can_view_analytics(user):
    return has_role_capability(user, "view_analytics")


def can_manage_departments(user):
    return has_role_capability(user, "manage_departments")


def can_manage_roles(user):
    return has_role_capability(user, "manage_roles")


def can_view(user, workorder: WorkOrder) -> bool:
    if not user.is_authenticated:
        return False
    return any(scope_matches(user, workorder, scope) for scope in allowed_view_scopes(user))


def can_create(user) -> bool:
    return user.is_authenticated and has_role_capability(user, "create_workorder")


def can_edit(user, workorder: WorkOrder) -> bool:
    if not can_view(user, workorder):
        return False
    return any(scope_matches(user, workorder, rule.get("edit_scope")) for rule in active_role_rules(user))


def can_delete(user, workorder: WorkOrder) -> bool:
    return can_edit(user, workorder)


def can_assign(user, workorder: WorkOrder) -> bool:
    return can_manage_assignments(user) and can_view(user, workorder)


def can_comment(user, workorder: WorkOrder) -> bool:
    if not can_view(user, workorder):
        return False
    return any(scope_matches(user, workorder, rule.get("comment_scope")) for rule in active_role_rules(user))


def can_upload_attachment(user, workorder: WorkOrder) -> bool:
    if not can_view(user, workorder):
        return False
    return any(scope_matches(user, workorder, rule.get("upload_attachment_scope")) for rule in active_role_rules(user))


def can_confirm_closure(user, workorder: WorkOrder) -> bool:
    if workorder.status != WorkOrderStatus.RESOLVED:
        return False
    if not can_view(user, workorder):
        return False
    return any(scope_matches(user, workorder, rule.get("confirm_closure_scope")) for rule in active_role_rules(user))


def can_rate(user, workorder: WorkOrder) -> bool:
    if workorder.status != WorkOrderStatus.CLOSED:
        return False
    if not can_view(user, workorder):
        return False
    return any(scope_matches(user, workorder, rule.get("rate_scope")) for rule in active_role_rules(user))


def can_transition(user, workorder: WorkOrder, target_status: str) -> bool:
    if not can_view(user, workorder):
        return False
    allowed = status_transitions().get(workorder.status, set())
    if target_status not in allowed:
        return False
    if target_status == WorkOrderStatus.CLOSED:
        return can_confirm_closure(user, workorder)
    for rule in active_role_rules(user):
        targets = rule.get("transition_targets", [])
        if targets != "*" and target_status not in targets:
            continue
        if scope_matches(user, workorder, rule.get("transition_scope")):
            return True
    return False
