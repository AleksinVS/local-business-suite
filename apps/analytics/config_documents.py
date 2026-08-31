from apps.analytics.contracts import (
    validate_analytics_business_facts_payload,
    validate_analytics_dedup_rules_payload,
    validate_analytics_diagnostic_playbooks_payload,
    validate_analytics_metrics_payload,
    validate_analytics_monitors_payload,
    validate_analytics_retention_profiles_payload,
    validate_analytics_scope_rules_payload,
    validate_analytics_sources_payload,
    validate_analytics_workflow_routes_payload,
    validate_dataset_registry_payload,
)
from apps.settings_center.document_specs import ConfigDocumentSpec


_VALIDATORS = {
    "analysis_scope_rules": validate_analytics_scope_rules_payload,
    "business_facts": validate_analytics_business_facts_payload,
    "datasets": validate_dataset_registry_payload,
    "dedup_rules": validate_analytics_dedup_rules_payload,
    "diagnostic_playbooks": validate_analytics_diagnostic_playbooks_payload,
    "metrics": validate_analytics_metrics_payload,
    "monitors": validate_analytics_monitors_payload,
    "retention_profiles": validate_analytics_retention_profiles_payload,
    "sources": validate_analytics_sources_payload,
    "workflow_routes": validate_analytics_workflow_routes_payload,
}


def get_document_specs():
    result = []
    for name, validator in _VALIDATORS.items():
        settings_path = (
            "LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE"
            if name == "analysis_scope_rules"
            else f"LOCAL_BUSINESS_ANALYTICS_{name.upper()}_FILE"
        )
        result.append(
            ConfigDocumentSpec(
                document_id=f"analytics.contract.{name}",
                domain="analytics",
                storage_policy="git_static",
                default_path=f"contracts/analytics/{name}.json",
                schema_version=1,
                validator=validator,
                failure_policy="fail_closed",
                write_policy="read_only",
                required_permission="manage_settings",
                owner="analytics",
                legacy_settings_path=settings_path,
                consumer_classes=("analytics",),
                sensitivity=(
                    "restricted"
                    if name in {"analysis_scope_rules", "retention_profiles", "sources"}
                    else "internal"
                ),
                active_backend="git",
            )
        )
    return result
