from __future__ import annotations

import copy
import json

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.core.contract_store import normalized_hash
from apps.core.json_utils import (
    atomic_write_json,
    load_json_file,
)
from apps.ai.contracts import (
    validate_ai_chat_settings_payload,
    validate_ai_registry_payload,
    validate_ai_task_types_payload,
    validate_ai_tools_payload,
)
from apps.memory.contracts import (
    validate_memory_file_organization_profiles_payload,
    validate_memory_profiles_payload,
    validate_memory_graph_schema_payload,
    validate_memory_ingestion_profiles_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
)
from apps.workorders.contracts import (
    validate_role_rules_payload,
    validate_workorder_status_colors_payload,
    validate_workflow_rules_payload,
)

from .models import SettingsChange
from .registry import get_registry
from .services import build_masked_diff, record_settings_change


VALIDATORS = {
    "validate_role_rules_payload": lambda payload: validate_role_rules_payload(
        payload,
        workflow_payload=load_json_file(settings.LOCAL_BUSINESS_WORKFLOW_RULES_FILE),
    ),
    "validate_workorder_status_colors_payload": lambda payload: validate_workorder_status_colors_payload(
        payload,
        workflow_payload=load_json_file(settings.LOCAL_BUSINESS_WORKFLOW_RULES_FILE),
    ),
    "validate_workflow_rules_payload": validate_workflow_rules_payload,
    "validate_ai_registry_payload": validate_ai_registry_payload,
    "validate_ai_tools_payload": validate_ai_tools_payload,
    "validate_ai_task_types_payload": validate_ai_task_types_payload,
    "validate_ai_chat_settings_payload": validate_ai_chat_settings_payload,
    "validate_memory_profiles_payload": validate_memory_profiles_payload,
    "validate_memory_routing_payload": validate_memory_routing_payload,
    "validate_memory_ingestion_profiles_payload": validate_memory_ingestion_profiles_payload,
    "validate_memory_file_organization_profiles_payload": validate_memory_file_organization_profiles_payload,
    "validate_memory_graph_schema_payload": validate_memory_graph_schema_payload,
    "validate_memory_sources_payload": lambda payload: validate_memory_sources_payload(
        payload,
        profiles_payload=load_json_file(settings.LOCAL_BUSINESS_MEMORY_PROFILES_FILE),
        routing_payload=load_json_file(settings.LOCAL_BUSINESS_MEMORY_ROUTING_FILE),
        ingestion_profiles_payload=load_json_file(settings.LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE),
    ),
}


def read_contract_value(descriptor):
    path = _contract_path(descriptor)
    return load_json_file(path)


def preview_contract_payload(*, descriptor, raw_payload: str):
    before = read_contract_value(descriptor)
    after = parse_and_validate_payload(descriptor, raw_payload)
    return {
        "before": before,
        "after": after,
        "masked_diff": build_masked_diff(before, after),
        "validation_result": {"valid": True},
    }


def apply_contract_payload(
    *, actor, setting_id: str, raw_payload: str, confirmed: bool, base_hash: str | None = None
):
    descriptor = get_registry().get(setting_id)
    if descriptor.storage_kind != "runtime_contract":
        raise ValidationError("Настройка не связана с рабочим контрактом.")
    if not descriptor.is_editable:
        raise ValidationError("Настройка недоступна для редактирования.")
    if not confirmed:
        raise ValidationError("Для изменения контракта нужно явное подтверждение.")

    before = read_contract_value(descriptor)
    # Оптимистическая проверка против потерянного обновления при конкурентной
    # правке: если вызывающий передал хеш прочитанной версии, а файл уже
    # изменился — отклоняем запись и предлагаем перечитать.
    if base_hash is not None and normalized_hash(before) != base_hash:
        raise ValidationError(
            "Контракт уже изменён другим процессом. Перечитайте актуальную версию "
            "и повторите изменение."
        )
    after = parse_and_validate_payload(descriptor, raw_payload)
    atomic_write_json(_contract_path(descriptor), after)
    return record_settings_change(
        actor=actor,
        descriptor=descriptor,
        action=SettingsChange.Action.APPLY,
        status=SettingsChange.Status.APPLIED,
        before=before,
        after=after,
        validation_result={"valid": True},
    )


def parse_and_validate_payload(descriptor, raw_payload: str):
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Некорректный JSON: {exc.msg}.") from exc
    payload = copy.deepcopy(payload)
    validator_name = descriptor.metadata.get("validator")
    validator = VALIDATORS.get(validator_name)
    if validator is None:
        raise ValidationError(f"Неизвестный валидатор контракта: '{validator_name}'.")
    validator(payload)
    return payload


def _contract_path(descriptor):
    setting_name = descriptor.metadata.get("settings_path")
    if not setting_name:
        raise ValidationError("Дескриптор не задает settings_path.")
    return getattr(settings, setting_name)
