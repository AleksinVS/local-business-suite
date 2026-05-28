from __future__ import annotations

import copy
import json

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.core.json_utils import (
    atomic_write_json,
    load_json_file,
    validate_ai_chat_settings_payload,
    validate_ai_registry_payload,
    validate_ai_task_types_payload,
    validate_ai_tools_payload,
    validate_memory_profiles_payload,
    validate_memory_graph_schema_payload,
    validate_memory_ingestion_profiles_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
    validate_role_rules_payload,
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
    "validate_workflow_rules_payload": validate_workflow_rules_payload,
    "validate_ai_registry_payload": validate_ai_registry_payload,
    "validate_ai_tools_payload": validate_ai_tools_payload,
    "validate_ai_task_types_payload": validate_ai_task_types_payload,
    "validate_ai_chat_settings_payload": validate_ai_chat_settings_payload,
    "validate_memory_profiles_payload": validate_memory_profiles_payload,
    "validate_memory_routing_payload": validate_memory_routing_payload,
    "validate_memory_ingestion_profiles_payload": validate_memory_ingestion_profiles_payload,
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


def apply_contract_payload(*, actor, setting_id: str, raw_payload: str, confirmed: bool):
    descriptor = get_registry().get(setting_id)
    if descriptor.storage_kind != "runtime_contract":
        raise ValidationError("Setting is not backed by a runtime contract.")
    if not descriptor.is_editable:
        raise ValidationError("Setting is not editable.")
    if not confirmed:
        raise ValidationError("Contract update requires explicit confirmation.")

    before = read_contract_value(descriptor)
    after = parse_and_validate_payload(descriptor, raw_payload)
    atomic_write_json(_contract_path(descriptor), after)
    _refresh_inprocess_setting(descriptor, after)
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
        raise ValidationError(f"Invalid JSON: {exc.msg}.") from exc
    payload = copy.deepcopy(payload)
    validator_name = descriptor.metadata.get("validator")
    validator = VALIDATORS.get(validator_name)
    if validator is None:
        raise ValidationError(f"Unknown contract validator '{validator_name}'.")
    validator(payload)
    return payload


def _contract_path(descriptor):
    setting_name = descriptor.metadata.get("settings_path")
    if not setting_name:
        raise ValidationError("Descriptor does not define settings_path.")
    return getattr(settings, setting_name)


def _refresh_inprocess_setting(descriptor, payload):
    settings_attr = descriptor.metadata.get("settings_payload_attr")
    if settings_attr:
        setattr(settings, settings_attr, payload)
