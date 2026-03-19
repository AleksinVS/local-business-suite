import json
from pathlib import Path

from django.core.exceptions import ValidationError


ROLE_SCOPE_VALUES = {
    "none",
    "all",
    "visible",
    "authored",
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
}

REQUIRED_WORKFLOW_KEYS = {
    "statuses",
    "transitions",
}

REQUIRED_INTEGRATION_KEYS = {
    "code",
    "name",
    "owner",
    "transport",
    "mode",
    "direction",
    "status",
    "source_of_truth",
    "payloads",
}

REQUIRED_DATASET_KEYS = {
    "code",
    "layer",
    "path",
    "owner",
    "refresh_mode",
    "grain",
    "schema_version",
    "description",
}

REQUIRED_TASK_BRIEF_KEYS = {
    "id",
    "title",
    "status",
    "requested_by",
    "target_modules",
    "objective",
    "constraints",
    "deliverables",
    "acceptance_checks",
}

REQUIRED_CHANGE_PLAN_KEYS = {
    "brief_id",
    "title",
    "status",
    "summary",
    "assumptions",
    "affected_files",
    "steps",
    "verification",
    "risks",
}


def pretty_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def load_json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ensure_non_empty_mapping(payload, label):
    if not isinstance(payload, dict) or not payload:
        raise ValidationError(f"{label} должна быть непустым JSON-объектом.")


def _ensure_list_of_strings(value, label):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"{label} должен быть непустым списком строк.")


def validate_role_rules_payload(payload, workflow_payload=None):
    _ensure_non_empty_mapping(payload, "Конфигурация ролей")
    known_statuses = set()
    if workflow_payload:
        known_statuses = set(workflow_payload.get("statuses", []))

    for role, config in payload.items():
        if not isinstance(config, dict):
            raise ValidationError(f"Роль '{role}' должна быть JSON-объектом.")
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


def validate_integration_registry_payload(payload):
    if not isinstance(payload, list):
        raise ValidationError("Реестр интеграций должен быть JSON-массивом.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Элемент интеграции #{index} должен быть JSON-объектом.")
        missing = REQUIRED_INTEGRATION_KEYS - set(item.keys())
        if missing:
            raise ValidationError(
                f"Интеграция '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )
        if not isinstance(item["payloads"], list):
            raise ValidationError(f"Интеграция '{item['code']}' должна содержать список payloads.")


def validate_dataset_registry_payload(payload):
    if not isinstance(payload, list):
        raise ValidationError("Реестр аналитических датасетов должен быть JSON-массивом.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Датасет #{index} должен быть JSON-объектом.")
        missing = REQUIRED_DATASET_KEYS - set(item.keys())
        if missing:
            raise ValidationError(
                f"Датасет '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )


def validate_task_brief_payload(payload):
    _ensure_non_empty_mapping(payload, "Task brief")
    missing = REQUIRED_TASK_BRIEF_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Task brief не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("target_modules", "constraints", "deliverables", "acceptance_checks"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле '{key}' в task brief должно быть списком.")


def validate_change_plan_payload(payload):
    _ensure_non_empty_mapping(payload, "Change plan")
    missing = REQUIRED_CHANGE_PLAN_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Change plan не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("assumptions", "affected_files", "steps", "verification", "risks"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле '{key}' в change plan должно быть списком.")

