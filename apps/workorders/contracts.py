"""Валидаторы доменных контрактов заявок (roles, workflow, цвета статусов).

Эти правила описывают предметную область нарядов-заказов: ролевые scope-права,
граф статусов workflow и палитру статусов на доске. По правилам 3 и 5 AGENTS.md
доменные правила живут в своём приложении, а не в ядре ``apps.core``. Универсальные
JSON-примитивы (``_ensure_*``) импортируются из ``apps.core.json_utils`` — обратной
зависимости нет, поэтому импорт безопасен.
"""
import re

from django.core.exceptions import ValidationError

from apps.core.json_utils import (
    _ensure_list_of_strings,
    _ensure_non_empty_mapping,
)


ROLE_SCOPE_VALUES = {
    "none",
    "all",
    "visible",
    "authored",
    "department_branch",
    "assigned",
    "assigned_or_unassigned",
    "assigned_or_unassigned_or_authored",
}

REQUIRED_ROLE_KEYS = {
    "view_scope",
    "create_workorder",
    "edit_scope",
    "comment_scope",
    "upload_attachment_scope",
    "confirm_closure_scope",
    "rate_scope",
    "transition_scope",
    "transition_targets",
    "manage_inventory",
    "manage_board_columns",
    "manage_assignments",
    "view_analytics",
    "manage_departments",
    "manage_roles",
}

BACKWARD_COMPAT_ROLE_DEFAULT_KEYS = {
    "view_analytics",
    "manage_departments",
    "manage_roles",
}

REQUIRED_WORKFLOW_KEYS = {
    "statuses",
    "transitions",
}


def validate_role_rules_payload(payload, workflow_payload=None):
    _ensure_non_empty_mapping(payload, "Конфигурация ролей")
    known_statuses = set()
    if workflow_payload:
        known_statuses = set(workflow_payload.get("statuses", []))

    for role, config in payload.items():
        if role == "$schema":
            continue
        if not isinstance(config, dict):
            raise ValidationError(f"Роль '{role}' должна быть JSON-объектом.")
        legacy_admin_value = bool(config.get("manage_inventory"))
        for key in BACKWARD_COMPAT_ROLE_DEFAULT_KEYS:
            config.setdefault(key, legacy_admin_value)
        missing = REQUIRED_ROLE_KEYS - set(config.keys())
        if missing:
            raise ValidationError(
                f"Роль '{role}' не содержит обязательные поля: {', '.join(sorted(missing))}."
            )
        for scope_key in (
            "view_scope",
            "edit_scope",
            "comment_scope",
            "upload_attachment_scope",
            "confirm_closure_scope",
            "rate_scope",
            "transition_scope",
        ):
            if config.get(scope_key) not in ROLE_SCOPE_VALUES:
                raise ValidationError(
                    f"У роли '{role}' поле '{scope_key}' содержит недопустимое значение."
                )
        targets = config.get("transition_targets")
        if targets == "*":
            continue
        if not isinstance(targets, list):
            raise ValidationError(
                f"У роли '{role}' поле transition_targets должно быть списком или '*'."
            )
        if known_statuses and set(targets) - known_statuses:
            invalid = ", ".join(sorted(set(targets) - known_statuses))
            raise ValidationError(
                f"У роли '{role}' указаны неизвестные статусы перехода: {invalid}."
            )


def validate_workflow_rules_payload(payload):
    _ensure_non_empty_mapping(payload, "Конфигурация workflow")
    missing = REQUIRED_WORKFLOW_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Конфигурация workflow не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    statuses = payload.get("statuses")
    _ensure_list_of_strings(statuses, "Поле statuses")
    transitions = payload.get("transitions")
    if not isinstance(transitions, dict):
        raise ValidationError("Поле transitions должно быть JSON-объектом.")
    status_set = set(statuses)
    missing_transition_nodes = status_set - set(transitions.keys())
    if missing_transition_nodes:
        raise ValidationError(
            "Для некоторых статусов отсутствует описание переходов: "
            + ", ".join(sorted(missing_transition_nodes))
            + "."
        )
    extra_transition_nodes = set(transitions.keys()) - status_set
    if extra_transition_nodes:
        raise ValidationError(
            "В transitions описаны неизвестные статусы: "
            + ", ".join(sorted(extra_transition_nodes))
            + "."
        )
    for source, targets in transitions.items():
        if not isinstance(targets, list):
            raise ValidationError(f"Статус '{source}' должен содержать список целевых статусов.")
        invalid_targets = set(targets) - status_set
        if invalid_targets:
            raise ValidationError(
                f"У статуса '{source}' указаны неизвестные целевые статусы: "
                + ", ".join(sorted(invalid_targets))
                + "."
            )


def validate_workorder_status_colors_payload(payload, workflow_payload=None):
    _ensure_non_empty_mapping(payload, "Конфигурация цветов статусов заявок")
    statuses = payload.get("statuses")
    if not isinstance(statuses, dict) or not statuses:
        raise ValidationError("Поле statuses должно быть непустым JSON-объектом.")

    known_statuses = set()
    if workflow_payload:
        known_statuses = set(workflow_payload.get("statuses", []))
        missing = known_statuses - set(statuses.keys())
        if missing:
            raise ValidationError(
                "Для некоторых статусов не заданы цвета: "
                + ", ".join(sorted(missing))
                + "."
            )
        extra = set(statuses.keys()) - known_statuses
        if extra:
            raise ValidationError(
                "В цветах описаны неизвестные статусы: "
                + ", ".join(sorted(extra))
                + "."
            )

    for status, config in statuses.items():
        if not isinstance(status, str) or not status:
            raise ValidationError("Код статуса должен быть непустой строкой.")
        if not isinstance(config, dict):
            raise ValidationError(f"Настройка статуса '{status}' должна быть JSON-объектом.")
        missing_keys = {"label", "color", "background"} - set(config.keys())
        if missing_keys:
            raise ValidationError(
                f"Настройка статуса '{status}' не содержит поля: "
                + ", ".join(sorted(missing_keys))
                + "."
            )
        for key in ("label",):
            if not isinstance(config.get(key), str) or not config.get(key).strip():
                raise ValidationError(f"Поле {key} у статуса '{status}' должно быть непустой строкой.")
        for key in ("color", "background"):
            value = config.get(key)
            if not isinstance(value, str) or not re.match(r"^#[0-9a-fA-F]{6}$", value):
                raise ValidationError(
                    f"Поле {key} у статуса '{status}' должно быть цветом HEX вида #RRGGBB."
                )
