from django.core.exceptions import ValidationError

from apps.ai.contracts import (
    validate_ai_chat_settings_payload,
    validate_ai_identity_model_alignment,
    validate_ai_registry_payload,
    validate_ai_task_types_payload,
    validate_ai_task_types_slot_coverage,
    validate_ai_task_types_tool_alignment,
    validate_ai_tools_drift,
    validate_ai_tools_payload,
    validate_ai_write_confirmation_alignment,
)
from apps.ai.tool_definitions import TOOLS
from apps.settings_center.document_specs import ConfigDocumentSpec


def validate_ai_registry_document(candidate):
    validate_ai_registry_payload(candidate)
    validate_ai_identity_model_alignment(candidate)


def validate_ai_tools_document(candidate):
    validate_ai_tools_payload(candidate)
    validate_ai_tools_drift(candidate, TOOLS)


def validate_ai_task_types_document(candidate):
    validate_ai_task_types_payload(candidate)
    validate_ai_task_types_slot_coverage(candidate)


def cross_validate_ai_task_types(candidate, related_payloads):
    tools = related_payloads["ai.contract.tools"]
    validate_ai_task_types_tool_alignment(candidate, tools)
    validate_ai_write_confirmation_alignment(candidate, tools)


def validate_ai_models_document(candidate):
    if not isinstance(candidate, list) or not candidate:
        raise ValidationError("Каталог моделей ИИ должен быть непустым списком.")
    ids = []
    defaults = 0
    for item in candidate:
        if not isinstance(item, dict):
            raise ValidationError("Каждая модель ИИ должна быть JSON-объектом.")
        for key in ("id", "name", "model", "base_url", "api_key_env"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValidationError(f"У модели ИИ отсутствует непустое поле '{key}'.")
        if type(item.get("default")) is not bool:
            raise ValidationError("Поле default модели ИИ должно быть boolean.")
        ids.append(item["id"])
        defaults += int(item["default"])
    if len(ids) != len(set(ids)):
        raise ValidationError("Каталог моделей ИИ содержит повторяющиеся id.")
    if defaults != 1:
        raise ValidationError("Каталог моделей ИИ должен содержать ровно одну default-модель.")


def _spec(
    document_id,
    filename,
    validator,
    storage_policy,
    *,
    write_policy="read_only",
    consumer_classes=(),
    failure_policy="fail_closed",
    cross_document_ids=(),
    cross_validator=None,
    delivery_scope="django",
):
    return ConfigDocumentSpec(
        document_id=document_id,
        domain="ai",
        storage_policy=storage_policy,
        default_path=f"contracts/ai/{filename}",
        schema_version=1,
        validator=validator,
        failure_policy=failure_policy,
        write_policy=write_policy,
        required_permission="manage_settings",
        owner="ai",
        legacy_settings_path=f"LOCAL_BUSINESS_AI_{filename[:-5].upper()}_FILE",
        cross_document_ids=cross_document_ids,
        cross_validator=cross_validator,
        consumer_classes=consumer_classes,
        delivery_scope=delivery_scope,
        sensitivity="restricted" if storage_policy == "git_static" else "internal",
        active_backend="git" if storage_policy == "git_static" else "legacy_file",
    )


def get_document_specs():
    return [
        _spec(
            "ai.contract.registry",
            "registry.json",
            validate_ai_registry_document,
            "git_static",
            consumer_classes=("ai",),
        ),
        _spec(
            "ai.contract.tools",
            "tools.json",
            validate_ai_tools_document,
            "git_static",
            consumer_classes=("ai", "agent_runtime"),
            delivery_scope="django+agent_runtime",
        ),
        _spec(
            "ai.contract.task_types",
            "task_types.json",
            validate_ai_task_types_document,
            "git_static",
            consumer_classes=("ai", "agent_runtime"),
            delivery_scope="django+agent_runtime",
            cross_document_ids=("ai.contract.tools",),
            cross_validator=cross_validate_ai_task_types,
        ),
        _spec(
            "ai.contract.models",
            "models.json",
            validate_ai_models_document,
            "git_static",
            consumer_classes=("ai", "agent_runtime"),
            delivery_scope="django+agent_runtime",
        ),
        _spec(
            "ai.contract.chat_settings",
            "chat_settings.json",
            validate_ai_chat_settings_payload,
            "database_override",
            write_policy="editable",
            consumer_classes=("ai",),
            failure_policy="visible_default_fallback",
        ),
    ]
