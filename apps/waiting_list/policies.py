from apps.workorders.policies import active_role_rules

from .selectors import waiting_list_view_scope

# Роль контракта, которой по умолчанию выданы права листа ожидания.
ROLE_DOCTOR = "doctor"


WAITING_LIST_TRANSITIONS = {
    "waiting": {"scheduled", "cancelled"},
    "scheduled": {"waiting", "confirmed", "cancelled"},
    "confirmed": {"cancelled"},
    "cancelled": set(),
}


def _active_rules(user, rules_payload=None):
    return active_role_rules(user, rules_payload=rules_payload)


def _scope_matches(user, entry, scope):
    if scope == "all":
        return True
    if scope == "authored":
        return bool(getattr(user, "pk", None) and entry.author_id == user.pk)
    return False


def _status_matches(value, status):
    return value == "*" or isinstance(value, list) and status in value


def _legacy_edit_grant(rule):
    if rule.get("name") == "superuser":
        return "all", "*"
    if rule.get("view_waiting_list") is True:
        return "authored", "*"
    return "none", []


def _edit_grant(rule):
    if "waiting_list_edit_scope" not in rule:
        return _legacy_edit_grant(rule)
    return (
        rule.get("waiting_list_edit_scope", "none"),
        rule.get("waiting_list_edit_statuses", []),
    )


def _transition_grant(rule):
    if "waiting_list_transition_scope" not in rule:
        scope, statuses = _legacy_edit_grant(rule)
        return scope, statuses, "*"
    return (
        rule.get("waiting_list_transition_scope", "none"),
        rule.get("waiting_list_transition_from_statuses", []),
        rule.get("waiting_list_transition_targets", []),
    )


def can_view_waiting_list(user, entry=None, *, rules_payload=None):
    rules = _active_rules(user, rules_payload=rules_payload)
    if entry is None:
        return any(waiting_list_view_scope(rule) != "none" for rule in rules)
    return any(
        _scope_matches(user, entry, waiting_list_view_scope(rule))
        for rule in rules
    )


def can_create_waiting_list(user, *, rules_payload=None):
    return any(
        rule.get("create_waiting_list") is True
        for rule in _active_rules(user, rules_payload)
    )


def can_edit_waiting_list_entry(user, entry, *, rules_payload=None):
    rules = _active_rules(user, rules_payload=rules_payload)
    visible = any(_scope_matches(user, entry, waiting_list_view_scope(rule)) for rule in rules)
    if not visible:
        return False
    for rule in rules:
        scope, statuses = _edit_grant(rule)
        if _scope_matches(user, entry, scope) and _status_matches(statuses, entry.status):
            return True
    return False


def allowed_waiting_list_transition_targets(user, entry, *, rules_payload=None):
    global_targets = WAITING_LIST_TRANSITIONS.get(entry.status, set())
    if not global_targets:
        return set()
    rules = _active_rules(user, rules_payload=rules_payload)
    visible = any(
        _scope_matches(user, entry, waiting_list_view_scope(rule))
        for rule in rules
    )
    if not visible:
        return set()
    allowed = set()
    for rule in rules:
        scope, source_statuses, targets = _transition_grant(rule)
        if not _scope_matches(user, entry, scope):
            continue
        if not _status_matches(source_statuses, entry.status):
            continue
        if targets == "*":
            allowed.update(global_targets)
        elif isinstance(targets, list):
            allowed.update(global_targets.intersection(targets))
    return allowed


def can_transition_waiting_list_entry(user, entry, to_status=None, *, rules_payload=None):
    targets = allowed_waiting_list_transition_targets(
        user, entry, rules_payload=rules_payload
    )
    return bool(targets) if to_status is None else to_status in targets
