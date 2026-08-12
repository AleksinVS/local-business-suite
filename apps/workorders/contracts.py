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

# Метаданные-ключи контракта ролей (не являются ролями). Ключи с префиксом "$"
# зарезервированы под служебные блоки: "$schema" — ссылка на JSON-схему,
# "$capabilities" — справочник прав с понятными названиями и комментариями
# для нетехнических пользователей (ADR-0034).
CAPABILITY_METADATA_KEY = "$capabilities"
CAPABILITY_TYPES = {"flag", "scope", "targets"}
CAPABILITY_SECTIONS = {"workorders", "organization", "ai_memory", "personal_data"}
CAPABILITY_RISKS = {"normal", "elevated", "critical"}


def _validate_capability_metadata(metadata):
    if not isinstance(metadata, dict):
        raise ValidationError("Блок $capabilities должен быть JSON-объектом.")
    for key, entry in metadata.items():
        if not isinstance(entry, dict):
            raise ValidationError(f"Описание права '{key}' должно быть JSON-объектом.")
        if entry.get("type") not in CAPABILITY_TYPES:
            raise ValidationError(
                f"У права '{key}' поле type должно быть одним из: "
                + ", ".join(sorted(CAPABILITY_TYPES))
                + "."
            )
        for field in ("label", "description", "section", "risk"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    f"У права '{key}' поле {field} должно быть непустой строкой."
                )
        if entry["section"] not in CAPABILITY_SECTIONS:
            raise ValidationError(
                f"У права '{key}' неизвестный раздел '{entry['section']}'."
            )
        if entry["risk"] not in CAPABILITY_RISKS:
            raise ValidationError(
                f"У права '{key}' неизвестный уровень риска '{entry['risk']}'."
            )


def validate_role_rules_payload(payload, workflow_payload=None):
    _ensure_non_empty_mapping(payload, "Конфигурация ролей")
    unknown_service_keys = sorted(
        key
        for key in payload
        if isinstance(key, str)
        and key.startswith("$")
        and key not in {"$schema", CAPABILITY_METADATA_KEY, "$administration"}
    )
    if unknown_service_keys:
        raise ValidationError(
            "Конфигурация ролей содержит неизвестные служебные блоки: "
            + ", ".join(unknown_service_keys)
            + "."
        )
    known_statuses = set()
    if workflow_payload:
        known_statuses = set(workflow_payload.get("statuses", []))

    role_names = {
        role
        for role, config in payload.items()
        if isinstance(role, str) and not role.startswith("$") and isinstance(config, dict)
    }
    administration = payload.get("$administration", {})
    if not isinstance(administration, dict):
        raise ValidationError("Блок $administration должен быть JSON-объектом.")
    allowlist = administration.get("role_assignment_allowlist", {})
    if not isinstance(allowlist, dict):
        raise ValidationError(
            "Поле $administration.role_assignment_allowlist должно быть JSON-объектом."
        )
    capability_metadata = payload.get(CAPABILITY_METADATA_KEY, {})
    if capability_metadata:
        _validate_capability_metadata(capability_metadata)
    for actor_role, target_roles in allowlist.items():
        if actor_role not in role_names:
            raise ValidationError(
                f"Allowlist назначения ссылается на неизвестную роль актора '{actor_role}'."
            )
        if not isinstance(target_roles, list) or not all(
            isinstance(role, str) and role for role in target_roles
        ):
            raise ValidationError(
                f"Allowlist роли '{actor_role}' должен содержать список непустых кодов ролей."
            )
        if len(target_roles) != len(set(target_roles)):
            raise ValidationError(
                f"Allowlist роли '{actor_role}' содержит повторяющиеся роли."
            )
        unknown_targets = sorted(set(target_roles) - role_names)
        if unknown_targets:
            raise ValidationError(
                f"Allowlist роли '{actor_role}' содержит неизвестные роли: "
                + ", ".join(unknown_targets)
                + "."
            )
        critical_targets = [
            role
            for role in target_roles
            if _role_has_critical_capability(payload[role], capability_metadata)
        ]
        if critical_targets:
            raise ValidationError(
                f"Allowlist роли '{actor_role}' содержит критичные роли: "
                + ", ".join(sorted(critical_targets))
                + ". Их может назначать только суперпользователь."
            )

    for role, config in payload.items():
        if role.startswith("$"):
            if role == CAPABILITY_METADATA_KEY:
                _validate_capability_metadata(config)
            continue
        if not isinstance(config, dict):
            raise ValidationError(f"Роль '{role}' должна быть JSON-объектом.")
        if capability_metadata:
            allowed_role_keys = set(capability_metadata) | {"display_name", "description"}
            unknown_role_keys = sorted(set(config) - allowed_role_keys)
            if unknown_role_keys:
                raise ValidationError(
                    f"Роль '{role}' содержит неизвестные права: "
                    + ", ".join(unknown_role_keys)
                    + "."
                )
            missing_capabilities = sorted(set(capability_metadata) - set(config))
            if missing_capabilities:
                raise ValidationError(
                    f"Роль '{role}' не содержит права из справочника: "
                    + ", ".join(missing_capabilities)
                    + "."
                )
            _validate_role_capability_values(role, config, capability_metadata)
        else:
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


def _role_has_critical_capability(config, metadata):
    if not isinstance(config, dict) or not isinstance(metadata, dict):
        return False
    for capability, value in config.items():
        definition = metadata.get(capability)
        if not isinstance(definition, dict) or definition.get("risk") != "critical":
            continue
        if value not in (None, False, "", "none", [], {}):
            return True
    return False


def _validate_role_capability_values(role, config, metadata):
    for capability, definition in metadata.items():
        value = config.get(capability)
        capability_type = definition.get("type")
        if capability_type == "flag" and type(value) is not bool:
            raise ValidationError(
                f"У роли '{role}' флаг '{capability}' должен быть логическим значением."
            )
        if capability_type == "scope" and value not in ROLE_SCOPE_VALUES:
            raise ValidationError(
                f"У роли '{role}' поле '{capability}' содержит недопустимую область доступа."
            )
        if capability_type == "targets":
            if value == "*":
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                raise ValidationError(
                    f"У роли '{role}' поле '{capability}' должно быть списком строк или '*'."
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
