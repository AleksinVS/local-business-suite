from apps.core.contract_store import get_contract

from .contracts import capability_values, resolve_capability_values_source

from .models import WorkOrder, WorkOrderStatus

ROLE_CUSTOMER = "customer"
ROLE_TECHNICIAN = "technician"
ROLE_MANAGER = "manager"
LEGACY_DEFAULT_BOARD_VIEW_ROLE = "default_board_viewer"
VIEWER_ROLE = "viewer"
# Backward-compatible import name for callers that still render the legacy
# source.  New phase logic must use VIEWER_ROLE and runtime_viewer_enabled.
DEFAULT_BOARD_VIEW_ROLE = LEGACY_DEFAULT_BOARD_VIEW_ROLE
DEFAULT_BOARD_VISIBILITY_GROUP = ROLE_CUSTOMER

SCOPE_LABELS = {
    "all": "Все записи",
    "department_branch": "Ветка подразделения",
    "assigned_or_unassigned_or_authored": "Свои, назначенные и неназначенные",
    "assigned_or_unassigned": "Назначенные и неназначенные",
    "assigned": "Только назначенные",
    "visible": "Все видимые",
    "authored": "Только созданные пользователем",
    "none": "Нет доступа",
}

# Запасной список булевых прав на случай, если рабочая копия контракта ещё не
# содержит блок $capabilities (например, деградация store на старый снимок).
FALLBACK_BOOLEAN_CAPABILITIES = (
    ("create_workorder", "Создание заявок", ""),
    ("manage_inventory", "Управление инвентарём", ""),
    ("manage_board_columns", "Управление досками", ""),
    ("manage_assignments", "Управление назначениями", ""),
    ("view_analytics", "Просмотр аналитики", ""),
    ("manage_departments", "Управление подразделениями", ""),
    ("manage_roles", "Управление ролями", ""),
    ("manage_settings", "Управление настройками", ""),
    ("manage_ai_skills", "Управление ИИ-навыками", ""),
    ("memory_organization_write", "Запись в память организации", ""),
    ("memory_organization_review", "Ревью памяти организации", ""),
    ("view_waiting_list", "Просмотр листа ожидания", ""),
    ("create_waiting_list", "Добавление в лист ожидания", ""),
)


def capability_flags(rules_payload=None):
    """Булевы права из справочника $capabilities контракта ролей.

    Возвращает список кортежей (ключ, название, комментарий) — единый источник
    для редактора ролей и для superuser_rules(). Если справочника в рабочей
    копии контракта нет, используется статический запасной список.
    """
    flags = [
        (key, label, description)
        for key, label, description, capability_type in capability_definitions(rules_payload=rules_payload)
        if capability_type == "flag"
    ]
    return flags or list(FALLBACK_BOOLEAN_CAPABILITIES)


def capability_definitions(*, rules_payload=None):
    """Метаданные всех прав для понятного отображения и редактирования в UI."""
    payload = rules_payload if isinstance(rules_payload, dict) else role_rules()
    metadata = payload.get("$capabilities")
    if not isinstance(metadata, dict):
        return [
            (key, label, description, "flag")
            for key, label, description in FALLBACK_BOOLEAN_CAPABILITIES
        ]
    return [
        (
            key,
            entry.get("label", key),
            entry.get("description", ""),
            entry.get("type", ""),
        )
        for key, entry in metadata.items()
        if isinstance(entry, dict)
    ]


def user_roles(user):
    if not user.is_authenticated:
        return set()
    return set(user.groups.values_list("name", flat=True))


def role_rules():
    return get_contract("role_rules")


def runtime_viewer_enabled(rules_payload=None):
    """The single migration phase predicate: valid runtime viewer presence."""
    rules = rules_payload if isinstance(rules_payload, dict) else role_rules()
    return VIEWER_ROLE in rules and isinstance(rules.get(VIEWER_ROLE), dict)


def legacy_default_viewer_enabled(rules_payload=None):
    return not runtime_viewer_enabled(rules_payload=rules_payload)


def workflow_rules():
    return get_contract("workflow_rules")


def status_transitions():
    return {
        status: set(targets)
        for status, targets in workflow_rules().get("transitions", {}).items()
    }


def active_role_rules(user, rules_payload=None):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return []
    rules = rules_payload if isinstance(rules_payload, dict) else role_rules()
    if getattr(user, "is_superuser", False):
        return [{"name": "superuser", **superuser_rules(rules_payload=rules)}]
    explicit_rules = [
        {"name": role, **rules[role]}
        for role in user_roles(user)
        if role in rules
    ]
    if explicit_rules:
        return explicit_rules
    if default_board_access_applies(user, rules_payload=rules):
        return [{"name": DEFAULT_BOARD_VIEW_ROLE, **default_board_view_rules(rules_payload=rules)}]
    return []


def default_board_access_applies(user, rules_payload=None):
    """Базовый read-only профиль только для активного пользователя без ролей."""

    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    rules = rules_payload if isinstance(rules_payload, dict) else role_rules()
    # The runtime contract is the phase marker for the migration.  A prepared
    # viewer group is deliberately inert while this role is absent.
    if runtime_viewer_enabled(rules_payload=rules):
        return False
    explicit_role_names = set(rules) & user_roles(user)
    return not explicit_role_names


def _populate_capability_type_defaults(rules, *, rules_payload, superuser):
    metadata = rules_payload.get("$capabilities", {})
    if not isinstance(metadata, dict):
        return rules
    for key, definition in metadata.items():
        if key in rules or not isinstance(definition, dict):
            continue
        capability_type = definition.get("type")
        if capability_type == "flag":
            rules[key] = bool(superuser)
        elif capability_type == "scope":
            source = resolve_capability_values_source(
                key,
                definition,
                metadata=metadata,
            )
            values = capability_values(source)
            rules[key] = "all" if superuser and "all" in values else "none"
        elif capability_type == "targets":
            source = resolve_capability_values_source(
                key,
                definition,
                metadata=metadata,
            )
            values = capability_values(source)
            rules[key] = "*" if superuser and "*" in values else []
    return rules


def default_board_view_rules(rules_payload=None):
    """Минимальный профиль: просмотр своей ветки без единого write-права."""

    rules = {
        "display_name": "Базовый просмотр канбана",
        "description": (
            "Доступ по умолчанию для пользователя без назначенной роли: "
            "только просмотр заявок ветки своего подразделения."
        ),
        "view_scope": "department_branch",
        "edit_scope": "none",
        "comment_scope": "none",
        "upload_attachment_scope": "none",
        "confirm_closure_scope": "none",
        "rate_scope": "none",
        "transition_scope": "none",
        "transition_targets": [],
    }
    payload = rules_payload if isinstance(rules_payload, dict) else role_rules()
    for key, _label, _description in capability_flags(rules_payload=payload):
        rules[key] = False
    return _populate_capability_type_defaults(rules, rules_payload=payload, superuser=False)


def superuser_rules(rules_payload=None):
    # Scope-поля заданы явно, а булевы права берутся из справочника контракта:
    # новое право автоматически включается суперпользователю, ручной список
    # больше не может отстать от контракта (ранее из-за этого суперпользователь
    # терял memory_organization_write/review).
    rules = {
        "view_scope": "all",
        "edit_scope": "all",
        "comment_scope": "visible",
        "upload_attachment_scope": "visible",
        "confirm_closure_scope": "all",
        "rate_scope": "all",
        "transition_scope": "all",
        "transition_targets": "*",
    }
    payload = rules_payload if isinstance(rules_payload, dict) else role_rules()
    for key, _label, _description in capability_flags(rules_payload=payload):
        rules[key] = True
    return _populate_capability_type_defaults(rules, rules_payload=payload, superuser=True)


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


def board_access_role_names():
    """Контрактные роли, допустимые в ресурсном ACL доски."""
    rules = role_rules()
    return tuple(
        sorted(
            key
            for key, config in rules.items()
            if not key.startswith("$")
            and isinstance(config, dict)
            and config.get("view_scope", "none") != "none"
        )
    )


def can_manage_board_access(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (getattr(user, "is_superuser", False) or can_manage_roles(user))
    )


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
