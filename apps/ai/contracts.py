"""Валидаторы доменных контрактов ИИ (реестр, инструменты, типы задач, чат).

Содержит правила предметной области ИИ-агента: реестр возможностей, каталог
инструментов, типы задач, настройки чата и семантические кросс-проверки
(drift инструментов, выравнивание allowed_tools, confirmation-семантика,
покрытие слотов, минимальные поля identity-модели). По правилам 3 и 5 AGENTS.md
эти доменные правила живут в приложении ``apps.ai``, а не в ядре.

Универсальный примитив ``_ensure_non_empty_mapping`` импортируется из
``apps.core.json_utils`` (обратной зависимости нет).
"""
from django.core.exceptions import ValidationError

from apps.core.json_utils import _ensure_non_empty_mapping


REQUIRED_AI_REGISTRY_KEYS = {
    "version",
    "name",
    "description",
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

REQUIRED_AI_CHAT_SETTINGS_ROOT_KEYS = {
    "schema_version",
    "defaults",
    "surfaces",
}

AI_CHAT_SURFACE_VALUES = {"full_page", "sidebar"}
AI_CHAT_SESSION_MODE_VALUES = {"default", "dedicated"}

# Minimum identity fields the runtime request identity model must carry, per
# the identity_model contract in contracts/ai/registry.json.
IDENTITY_MINIMUM_FIELDS = frozenset({
    "user_id",
    "roles",
    "session_id",
    "conversation_id",
    "request_id",
})


def validate_ai_registry_payload(payload):
    _ensure_non_empty_mapping(payload, "Реестр ИИ")
    missing = REQUIRED_AI_REGISTRY_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Реестр ИИ не содержит обязательные поля: {', '.join(sorted(missing))}."
        )


def validate_ai_tools_payload(payload):
    _ensure_non_empty_mapping(payload, "Инструменты ИИ")
    missing = REQUIRED_AI_TOOLS_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Реестр инструментов ИИ не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValidationError("Реестр инструментов ИИ должен содержать непустой список tools.")
    for item in tools:
        if not isinstance(item, dict):
            raise ValidationError("Каждый инструмент ИИ должен быть JSON-объектом.")
        missing_item_keys = REQUIRED_AI_TOOL_KEYS - set(item.keys())
        if missing_item_keys:
            raise ValidationError(
                f"Инструмент ИИ '{item.get('id', 'unknown')}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_item_keys))}."
            )
        for key in ("inputs", "outputs"):
            if not isinstance(item.get(key), list):
                raise ValidationError(f"Поле '{key}' у инструмента ИИ '{item['id']}' должно быть списком.")
        input_schemas = item.get("input_schemas")
        if input_schemas:
            if not isinstance(input_schemas, dict):
                raise ValidationError(
                    f"Поле input_schemas у инструмента ИИ '{item['id']}' должно быть JSON-объектом."
                )
            input_names = set(item.get("inputs", []))
            for schema_key in input_schemas:
                if schema_key not in input_names:
                    raise ValidationError(
                        f"Инструмент ИИ '{item['id']}' содержит input_schema '{schema_key}', "
                        f"которого нет в списке inputs."
                    )


def validate_ai_task_types_payload(payload):
    _ensure_non_empty_mapping(payload, "Типы задач ИИ")
    missing = REQUIRED_AI_TASK_TYPES_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Реестр типов задач ИИ не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    task_types = payload.get("task_types")
    if not isinstance(task_types, list) or not task_types:
        raise ValidationError("Реестр типов задач ИИ должен содержать непустой список task_types.")
    for item in task_types:
        if not isinstance(item, dict):
            raise ValidationError("Каждый тип задачи ИИ должен быть JSON-объектом.")
        missing_item_keys = REQUIRED_AI_TASK_TYPE_KEYS - set(item.keys())
        if missing_item_keys:
            raise ValidationError(
                f"Тип задачи ИИ '{item.get('id', 'unknown')}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_item_keys))}."
            )
        for key in ("allowed_tools", "example_requests"):
            if not isinstance(item.get(key), list):
                raise ValidationError(f"Поле '{key}' у типа задачи ИИ '{item['id']}' должно быть списком.")


def validate_ai_chat_settings_payload(payload):
    _ensure_non_empty_mapping(payload, "Настройки ИИ-чата")
    missing = REQUIRED_AI_CHAT_SETTINGS_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Настройки ИИ-чата не содержат обязательные поля: {', '.join(sorted(missing))}."
        )
    if str(payload.get("schema_version")) != "1":
        raise ValidationError("Настройки ИИ-чата поддерживают только schema_version='1'.")
    defaults = payload.get("defaults")
    surfaces = payload.get("surfaces")
    if not isinstance(defaults, dict) or not defaults:
        raise ValidationError("Настройки ИИ-чата.defaults должны быть непустым JSON-объектом.")
    if not isinstance(surfaces, dict) or not surfaces:
        raise ValidationError("Настройки ИИ-чата.surfaces должны быть непустым JSON-объектом.")
    _validate_ai_chat_settings_block(defaults, "defaults", require_common=True)
    for surface, config in surfaces.items():
        if surface not in AI_CHAT_SURFACE_VALUES:
            raise ValidationError(f"Настройки ИИ-чата содержат неизвестную поверхность: {surface}.")
        if not isinstance(config, dict):
            raise ValidationError(f"Настройки ИИ-чата.surfaces.{surface} должны быть JSON-объектом.")
        _validate_ai_chat_settings_block(config, f"surfaces.{surface}", require_common=False)


def _validate_ai_chat_settings_block(config, label, *, require_common):
    common_keys = {
        "recent_message_limit",
        "summary_enabled",
        "summary_trigger_messages",
        "max_prompt_chars",
        "context_tool_enabled",
    }
    if require_common:
        missing = common_keys - set(config.keys())
        if missing:
            raise ValidationError(f"Настройки ИИ-чата.{label} не содержат поля: {', '.join(sorted(missing))}.")
    allowed_keys = common_keys | {"session_mode", "session_switcher"}
    unknown = set(config.keys()) - allowed_keys
    if unknown:
        raise ValidationError(f"Настройки ИИ-чата.{label} содержат неизвестные поля: {', '.join(sorted(unknown))}.")

    if "recent_message_limit" in config:
        value = config["recent_message_limit"]
        if type(value) is not int or value < 4 or value > 50:
            raise ValidationError(f"Настройки ИИ-чата.{label}.recent_message_limit должен быть целым числом в диапазоне 4..50.")
    if "summary_enabled" in config and type(config["summary_enabled"]) is not bool:
        raise ValidationError(f"Настройки ИИ-чата.{label}.summary_enabled должен быть boolean.")
    if "summary_trigger_messages" in config:
        value = config["summary_trigger_messages"]
        if type(value) is not int or value < 4 or value > 200:
            raise ValidationError(
                f"Настройки ИИ-чата.{label}.summary_trigger_messages должен быть целым числом в диапазоне 4..200."
            )
    if "max_prompt_chars" in config:
        value = config["max_prompt_chars"]
        if type(value) is not int or value < 1000 or value > 100000:
            raise ValidationError(f"Настройки ИИ-чата.{label}.max_prompt_chars должен быть целым числом в диапазоне 1000..100000.")
    if "context_tool_enabled" in config and type(config["context_tool_enabled"]) is not bool:
        raise ValidationError(f"Настройки ИИ-чата.{label}.context_tool_enabled должен быть boolean.")
    if "session_mode" in config and config["session_mode"] not in AI_CHAT_SESSION_MODE_VALUES:
        raise ValidationError(
            f"Настройки ИИ-чата.{label}.session_mode должен быть одним из: {', '.join(sorted(AI_CHAT_SESSION_MODE_VALUES))}."
        )
    if "session_switcher" in config and type(config["session_switcher"]) is not bool:
        raise ValidationError(f"Настройки ИИ-чата.{label}.session_switcher должен быть boolean.")


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
