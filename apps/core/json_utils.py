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

REQUIRED_AI_REGISTRY_KEYS = {
    "version",
    "name",
    "description",
    "primary_chat_ui",
    "agent_orchestrator",
    "tool_protocol",
    "tool_catalog",
    "task_type_catalog",
    "identity_model",
    "execution_policy",
}

REQUIRED_AI_TOOLS_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "default_policies",
    "tools",
}

REQUIRED_AI_TOOL_KEYS = {
    "id",
    "title",
    "domain",
    "mode",
    "execution_mode",
    "description",
    "inputs",
    "outputs",
    "required_role_scope",
}

REQUIRED_AI_TASK_TYPES_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "task_types",
}

REQUIRED_AI_TASK_TYPE_KEYS = {
    "id",
    "title",
    "mode",
    "description",
    "allowed_tools",
    "requires_confirmation",
    "output_mode",
    "example_requests",
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
        if role == "$schema":
            continue
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


def validate_ai_registry_payload(payload):
    _ensure_non_empty_mapping(payload, "AI registry")
    missing = REQUIRED_AI_REGISTRY_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"AI registry не содержит обязательные поля: {', '.join(sorted(missing))}."
        )


def validate_ai_tools_payload(payload):
    _ensure_non_empty_mapping(payload, "AI tools")
    missing = REQUIRED_AI_TOOLS_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"AI tools registry не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValidationError("AI tools registry должен содержать непустой список tools.")
    for item in tools:
        if not isinstance(item, dict):
            raise ValidationError("Каждый AI tool должен быть JSON-объектом.")
        missing_item_keys = REQUIRED_AI_TOOL_KEYS - set(item.keys())
        if missing_item_keys:
            raise ValidationError(
                f"AI tool '{item.get('id', 'unknown')}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_item_keys))}."
            )
        for key in ("inputs", "outputs"):
            if not isinstance(item.get(key), list):
                raise ValidationError(f"Поле '{key}' у AI tool '{item['id']}' должно быть списком.")


def validate_ai_task_types_payload(payload):
    _ensure_non_empty_mapping(payload, "AI task types")
    missing = REQUIRED_AI_TASK_TYPES_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"AI task type registry не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    task_types = payload.get("task_types")
    if not isinstance(task_types, list) or not task_types:
        raise ValidationError("AI task type registry должен содержать непустой список task_types.")
    for item in task_types:
        if not isinstance(item, dict):
            raise ValidationError("Каждый AI task type должен быть JSON-объектом.")
        missing_item_keys = REQUIRED_AI_TASK_TYPE_KEYS - set(item.keys())
        if missing_item_keys:
            raise ValidationError(
                f"AI task type '{item.get('id', 'unknown')}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_item_keys))}."
            )
        for key in ("allowed_tools", "example_requests"):
            if not isinstance(item.get(key), list):
                raise ValidationError(f"Поле '{key}' у AI task type '{item['id']}' должно быть списком.")


def validate_ai_tools_drift(json_payload, canonical_tools):
    canonical_by_id = {tool["id"]: tool for tool in canonical_tools}
    json_by_id = {tool["id"]: tool for tool in json_payload.get("tools", [])}

    for tool_id, canonical_tool in canonical_by_id.items():
        if tool_id not in json_by_id:
            raise ValidationError(f"Tool '{tool_id}' is missing in JSON registry.")
        json_tool = json_by_id[tool_id]

        for key in REQUIRED_AI_TOOL_KEYS:
            if canonical_tool.get(key) != json_tool.get(key):
                raise ValidationError(
                    f"Tool '{tool_id}' field '{key}' differs: canonical={canonical_tool.get(key)!r}, json={json_tool.get(key)!r}."
                )


def validate_ai_task_types_tool_alignment(task_types_payload, tools_payload):
    """
    Validate that every tool referenced in task_types[].allowed_tools exists
    in the tool catalog.

    This catches drift where a task type declares a tool that was removed or
    renamed in the tool catalog — before runtime.
    """
    tool_ids_in_catalog = {tool["id"] for tool in tools_payload.get("tools", [])}
    task_types = task_types_payload.get("task_types", [])
    for task_type in task_types:
        tt_id = task_type.get("id", "unknown")
        for tool_id in task_type.get("allowed_tools", []):
            if tool_id not in tool_ids_in_catalog:
                raise ValidationError(
                    f"Task type '{tt_id}' declares allowed_tool '{tool_id}' "
                    f"which does not exist in the tool catalog."
                )


def validate_ai_write_confirmation_alignment(task_types_payload, tools_payload):
    """
    Validate that write-mode task types and their write-mode tools have
    aligned requires_confirmation semantics.

    If a write tool declares requires_confirmation=True, all task types that
    use it exclusively for write operations should also require confirmation.
    This catches misalignment between tool-level and task-type-level policy.
    """
    tool_by_id = {tool["id"]: tool for tool in tools_payload.get("tools", [])}
    task_types = task_types_payload.get("task_types", [])

    for task_type in task_types:
        tt_id = task_type.get("id", "unknown")
        mode = task_type.get("mode", "")
        tt_requires_confirmation = task_type.get("requires_confirmation", False)

        if mode != "write":
            continue

        for tool_id in task_type.get("allowed_tools", []):
            tool = tool_by_id.get(tool_id, {})
            if tool.get("mode") != "write":
                continue
            tool_requires_confirmation = tool.get("requires_confirmation", False)
            if tool_requires_confirmation != tt_requires_confirmation:
                raise ValidationError(
                    f"Task type '{tt_id}' (mode=write) has requires_confirmation={tt_requires_confirmation} "
                    f"but its write tool '{tool_id}' has requires_confirmation={tool_requires_confirmation}. "
                    f"These must be aligned for write-mode task types."
                )


def validate_ai_task_types_slot_coverage(task_types_payload):
    """
    Validate that within each task type, required_slots and optional_slots
    are disjoint sets (a slot cannot be both required and optional).

    Also validates that required_slots does not contain duplicates.
    """
    task_types = task_types_payload.get("task_types", [])
    for task_type in task_types:
        tt_id = task_type.get("id", "unknown")
        required = set(task_type.get("required_slots", []))
        optional = set(task_type.get("optional_slots", []))

        overlap = required & optional
        if overlap:
            raise ValidationError(
                f"Task type '{tt_id}' has slots that are both required and optional: "
                f"{sorted(overlap)}. Required and optional slot sets must be disjoint."
            )

        if len(required) != len(task_type.get("required_slots", [])):
            raise ValidationError(
                f"Task type '{tt_id}' has duplicate entries in required_slots."
            )


# Minimum identity fields the runtime request identity model must carry, per
# the identity_model contract in config/ai/registry.json.
IDENTITY_MINIMUM_FIELDS = frozenset({
    "user_id",
    "roles",
    "session_id",
    "conversation_id",
    "request_id",
})


def validate_ai_identity_model_alignment(registry_payload):
    """
    Validate that the identity_model.minimum_fields declared in the AI registry
    include all fields required by the runtime request identity model.

    The Django chat surface and gateway client must carry: user_id, roles,
    session_id, conversation_id, request_id.  Any missing field is a
    contract violation that breaks trace correlation.
    """
    identity_model = registry_payload.get("identity_model", {})
    minimum_fields = set(identity_model.get("minimum_fields", []))
    missing = IDENTITY_MINIMUM_FIELDS - minimum_fields
    if missing:
        raise ValidationError(
            f"AI registry identity_model.minimum_fields is missing required fields: "
            f"{', '.join(sorted(missing))}. "
            f"The runtime request identity model must carry these to enable trace correlation."
        )
