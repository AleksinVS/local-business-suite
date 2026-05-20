from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ai.tool_definitions import TOOLS
from apps.core.json_utils import (
    load_json_file,
    validate_ai_identity_model_alignment,
    validate_ai_registry_payload,
    validate_ai_task_types_payload,
    validate_ai_task_types_slot_coverage,
    validate_ai_task_types_tool_alignment,
    validate_ai_tools_drift,
    validate_ai_tools_payload,
    validate_ai_write_confirmation_alignment,
    validate_change_plan_payload,
    validate_dataset_registry_payload,
    validate_integration_registry_payload,
    validate_memory_profiles_payload,
    validate_memory_graph_schema_payload,
    validate_memory_ingestion_profiles_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
    validate_role_rules_payload,
    validate_task_brief_payload,
    validate_workflow_rules_payload,
)
from services.agent_runtime.task_types import STATUS_ALIASES


class Command(BaseCommand):
    help = "Validate AI-first / Code-first JSON contracts used by the project."

    def handle(self, *args, **options):
        workflow_payload = load_json_file(settings.LOCAL_BUSINESS_WORKFLOW_RULES_FILE)
        validate_workflow_rules_payload(workflow_payload)
        role_payload = load_json_file(settings.LOCAL_BUSINESS_ROLE_RULES_FILE)
        validate_role_rules_payload(role_payload, workflow_payload=workflow_payload)
        validate_integration_registry_payload(load_json_file(settings.LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE))
        validate_dataset_registry_payload(load_json_file(settings.LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE))
        validate_task_brief_payload(load_json_file(settings.LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE))
        validate_change_plan_payload(load_json_file(settings.LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE))
        registry_payload = load_json_file(settings.LOCAL_BUSINESS_AI_REGISTRY_FILE)
        validate_ai_registry_payload(registry_payload)
        validate_ai_identity_model_alignment(registry_payload)
        tools_payload = load_json_file(settings.LOCAL_BUSINESS_AI_TOOLS_FILE)
        validate_ai_tools_payload(tools_payload)
        validate_ai_tools_drift(tools_payload, TOOLS)
        task_types_payload = load_json_file(settings.LOCAL_BUSINESS_AI_TASK_TYPES_FILE)
        validate_ai_task_types_payload(task_types_payload)
        # Semantic cross-cut validators — catch contract drift before runtime.
        validate_ai_task_types_tool_alignment(task_types_payload, tools_payload)
        validate_ai_write_confirmation_alignment(task_types_payload, tools_payload)
        validate_ai_task_types_slot_coverage(task_types_payload)
        memory_profiles_payload = load_json_file(settings.LOCAL_BUSINESS_MEMORY_PROFILES_FILE)
        validate_memory_profiles_payload(memory_profiles_payload)
        memory_routing_payload = load_json_file(settings.LOCAL_BUSINESS_MEMORY_ROUTING_FILE)
        validate_memory_routing_payload(memory_routing_payload)
        memory_ingestion_profiles_payload = load_json_file(settings.LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE)
        validate_memory_ingestion_profiles_payload(memory_ingestion_profiles_payload)
        validate_memory_graph_schema_payload(load_json_file(settings.LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE))
        validate_memory_sources_payload(
            load_json_file(settings.LOCAL_BUSINESS_MEMORY_SOURCES_FILE),
            profiles_payload=memory_profiles_payload,
            routing_payload=memory_routing_payload,
            ingestion_profiles_payload=memory_ingestion_profiles_payload,
        )
        # Validate STATUS_ALIASES keys align with workflow_rules statuses.
        workflow_statuses = set(workflow_payload.get("statuses", []))
        alias_keys = set(STATUS_ALIASES.keys())
        if alias_keys != workflow_statuses:
            missing_in_aliases = workflow_statuses - alias_keys
            extra_in_aliases = alias_keys - workflow_statuses
            msg_parts = []
            if missing_in_aliases:
                msg_parts.append(f"missing from STATUS_ALIASES: {sorted(missing_in_aliases)}")
            if extra_in_aliases:
                msg_parts.append(f"extra in STATUS_ALIASES: {sorted(extra_in_aliases)}")
            from django.core.exceptions import ValidationError
            raise ValidationError(
                f"STATUS_ALIASES keys do not match workflow_rules.json statuses: {'; '.join(msg_parts)}."
            )
        self.stdout.write(self.style.SUCCESS("Architecture contracts are valid."))
