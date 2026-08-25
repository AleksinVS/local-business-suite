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

# Values used by the explicit waiting-list capability model.  These are kept
# here, next to the role-contract validator, so the editor and future domain
# policies cannot silently invent a second vocabulary.
WAITING_LIST_SCOPE_VALUES = ("none", "authored", "all")
WAITING_LIST_STATUS_VALUES = ("waiting", "scheduled", "confirmed", "cancelled")
WORKORDER_STATUS_VALUES = (
    "new",
    "accepted",
    "in_progress",
    "on_hold",
    "resolved",
    "closed",
    "cancelled",
)
CAPABILITY_VALUES_SOURCES = {
    "workorder_scopes",
    "waiting_list_scopes",
    "workorder_statuses",
    "waiting_list_statuses",
}
CAPABILITY_VALUES_WILDCARD_SOURCES = {"workorder_statuses", "waiting_list_statuses"}

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
CAPABILITY_SECTIONS = {"workorders", "organization", "ai_memory", "personal_data", "waiting_list"}
CAPABILITY_RISKS = {"normal", "elevated", "critical"}
LEGACY_CAPABILITY_SOURCES = {
    "view_scope": "workorder_scopes",
    "edit_scope": "workorder_scopes",
    "comment_scope": "workorder_scopes",
    "upload_attachment_scope": "workorder_scopes",
    "confirm_closure_scope": "workorder_scopes",
    "rate_scope": "workorder_scopes",
    "transition_scope": "workorder_scopes",
    "transition_targets": "workorder_statuses",
}


def is_legacy_capability_metadata(metadata):
    return (
        isinstance(metadata, dict)
        and "view_waiting_list" in metadata
        and not any(key.startswith("waiting_list_") for key in metadata)
    )


def resolve_capability_values_source(capability, definition, *, metadata=None):
    legacy_compat = is_legacy_capability_metadata(metadata)
    source = definition.get("values_source")
    if source is None and legacy_compat:
        source = LEGACY_CAPABILITY_SOURCES.get(capability)
    if definition.get("type") != "flag" and source not in CAPABILITY_VALUES_SOURCES:
        raise ValidationError(
            f"У права '{capability}' должно быть известное поле values_source."
        )
    return source


def _validate_capability_metadata(metadata, *, legacy_compat=False):
    if not isinstance(metadata, dict):
        raise ValidationError("Блок $capabilities должен быть JSON-объектом.")
    allowed_fields = {"type", "label", "description", "section", "risk", "values_source"}
    for key, entry in metadata.items():
        if not isinstance(key, str) or not key or key.startswith("$"):
            raise ValidationError(f"Код права '{key}' должен быть непустой строкой без префикса '$'.")
        if not isinstance(entry, dict):
            raise ValidationError(f"Описание права '{key}' должно быть JSON-объектом.")
        unknown_fields = sorted(set(entry) - allowed_fields)
        if unknown_fields:
            raise ValidationError(
                f"Описание права '{key}' содержит неизвестные поля: "
                + ", ".join(unknown_fields)
                + "."
            )
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
        values_source = resolve_capability_values_source(
            key,
            entry,
            metadata=metadata if legacy_compat else None,
        )
        if entry["type"] == "flag":
            if "values_source" in entry:
                raise ValidationError(
                    f"У булева права '{key}' поле values_source запрещено."
                )
        elif values_source not in CAPABILITY_VALUES_SOURCES:
            raise ValidationError(
                f"У права '{key}' должно быть известное поле values_source."
            )


def capability_values(source, *, workflow_payload=None):
    """Return the canonical values for a capability ``values_source``.

    ``workflow_payload`` is optional for callers that validate a role contract
    without loading the workflow contract.  The normal read path uses the
    canonical fallback list; the write path supplies the workflow payload and
    therefore validates against its current status list.
    """
    if source == "workorder_scopes":
        return tuple(sorted(ROLE_SCOPE_VALUES))
    if source == "waiting_list_scopes":
        return WAITING_LIST_SCOPE_VALUES
    if source == "waiting_list_statuses":
        return (*WAITING_LIST_STATUS_VALUES, "*")
    if source == "workorder_statuses":
        if isinstance(workflow_payload, dict):
            statuses = workflow_payload.get("statuses", ())
            if isinstance(statuses, list) and all(
                isinstance(status, str) and status for status in statuses
            ):
                return (*statuses, "*")
        # The role contract is also read independently by ContractStore.  Keep
        # that read path deterministic while the write path still cross-checks
        # against the current workflow contract.
        return (*WORKORDER_STATUS_VALUES, "*")
    raise ValidationError(f"Неизвестный источник значений capability: {source!r}.")


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

    administration = payload.get("$administration", {})
    if not isinstance(administration, dict):
        raise ValidationError("Блок $administration должен быть JSON-объектом.")
    capability_metadata = payload.get(CAPABILITY_METADATA_KEY, {})
    legacy_compat = is_legacy_capability_metadata(capability_metadata)
    if capability_metadata:
        _validate_capability_metadata(capability_metadata, legacy_compat=legacy_compat)
    for role, config in payload.items():
        if role.startswith("$"):
            if role == CAPABILITY_METADATA_KEY:
                _validate_capability_metadata(config, legacy_compat=legacy_compat)
            continue
        if not isinstance(config, dict):
            raise ValidationError(f"Роль '{role}' должна быть JSON-объектом.")
        if capability_metadata:
            allowed_role_keys = set(capability_metadata) | {
                "display_name",
                "description",
                "protected",
            }
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
            _validate_role_capability_values(
                role,
                config,
                capability_metadata,
                workflow_payload=workflow_payload,
                legacy_compat=legacy_compat,
            )
        else:
            legacy_admin_value = bool(config.get("manage_inventory"))
            for key in BACKWARD_COMPAT_ROLE_DEFAULT_KEYS:
                config.setdefault(key, legacy_admin_value)
        if "protected" in config and type(config["protected"]) is not bool:
            raise ValidationError(
                f"У роли '{role}' protected должен быть логическим значением."
            )
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


def _validate_role_capability_values(
    role,
    config,
    metadata,
    *,
    workflow_payload=None,
    legacy_compat=False,
):
    for capability, definition in metadata.items():
        value = config.get(capability)
        capability_type = definition.get("type")
        if capability_type == "flag" and type(value) is not bool:
            raise ValidationError(
                f"У роли '{role}' флаг '{capability}' должен быть логическим значением."
            )
        if capability_type == "scope":
            source = resolve_capability_values_source(
                capability,
                definition,
                metadata=metadata if legacy_compat else None,
            )
            allowed = set(capability_values(source, workflow_payload=workflow_payload))
            if value not in allowed:
                raise ValidationError(
                    f"У роли '{role}' поле '{capability}' содержит недопустимое значение."
                )
        if capability_type == "targets":
            source = resolve_capability_values_source(
                capability,
                definition,
                metadata=metadata if legacy_compat else None,
            )
            allowed = set(capability_values(source, workflow_payload=workflow_payload))
            if value == "*":
                if source not in CAPABILITY_VALUES_WILDCARD_SOURCES:
                    raise ValidationError(
                        f"У роли '{role}' wildcard для права '{capability}' запрещён."
                    )
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item in allowed for item in value
            ):
                raise ValidationError(
                    f"У роли '{role}' поле '{capability}' содержит неизвестное значение."
                )
            if len(value) != len(set(value)):
                raise ValidationError(
                    f"У роли '{role}' поле '{capability}' содержит повторяющиеся значения."
                )
            if "*" in value:
                raise ValidationError(
                    f"У роли '{role}' wildcard должен передаваться отдельно для права '{capability}'."
                )

    _validate_waiting_list_invariants(role, config, metadata)


def _validate_waiting_list_invariants(role, config, metadata):
    """Validate related waiting-list fields as one grant, not independently."""
    waiting_fields = {
        "waiting_list_edit_scope",
        "waiting_list_edit_statuses",
        "waiting_list_transition_scope",
        "waiting_list_transition_from_statuses",
        "waiting_list_transition_targets",
    }
    if not waiting_fields.intersection(metadata):
        return
    edit_scope = config.get("waiting_list_edit_scope")
    edit_statuses = config.get("waiting_list_edit_statuses")
    if edit_scope == "none" and edit_statuses != []:
        raise ValidationError(
            f"У роли '{role}' область редактирования листа ожидания 'none' требует пустого списка статусов."
        )
    if edit_scope != "none" and not isinstance(edit_statuses, list) and edit_statuses != "*":
        raise ValidationError(
            f"У роли '{role}' область редактирования листа ожидания требует статусы."
        )
    if edit_scope != "none" and isinstance(edit_statuses, list) and not edit_statuses:
        raise ValidationError(
            f"У роли '{role}' область редактирования листа ожидания требует непустого списка статусов."
        )

    transition_scope = config.get("waiting_list_transition_scope")
    from_statuses = config.get("waiting_list_transition_from_statuses")
    targets = config.get("waiting_list_transition_targets")
    if transition_scope == "none" and (from_statuses != [] or targets != []):
        raise ValidationError(
            f"У роли '{role}' отключённый переход листа ожидания требует пустых списков статусов."
        )
    if transition_scope != "none":
        for field, value in (
            ("waiting_list_transition_from_statuses", from_statuses),
            ("waiting_list_transition_targets", targets),
        ):
            if isinstance(value, list) and value:
                continue
            if value == "*":
                continue
            raise ValidationError(
                f"У роли '{role}' область перехода листа ожидания требует непустого списка '{field}'."
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
