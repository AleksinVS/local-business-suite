from django.conf import settings

from apps.core.json_utils import load_json_file
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


def get_analytics_document_payload(name, *, snapshots=None, request=None):
    """Return one immutable analytics contract payload.

    Analytics contracts are ``git_static`` documents.  Runtime consumers must
    therefore read them through the settings-center repository rather than
    treating legacy file settings as a second writable store.  The narrow
    Django test override below exists only for the existing fixture suite,
    which supplies temporary contract files through ``override_settings``.
    """

    document_id = f"analytics.contract.{name}"
    # Test fixtures intentionally replace the legacy path.  Keep that
    # compatibility isolated in the adapter; production settings resolve to
    # the Git default via ConfigDocumentRepository.
    wrapped = getattr(settings, "_wrapped", None)
    legacy_name = _legacy_setting_name(name)
    if (
        wrapped is not None
        and wrapped.__class__.__name__ == "UserSettingsHolder"
        and legacy_name in getattr(wrapped, "__dict__", {})
    ):
        return load_json_file(getattr(wrapped, legacy_name))
    if snapshots is None:
        from apps.settings_center.document_repository import get_snapshot

        snapshots = get_snapshot((document_id,), request=request)
    snapshot = snapshots[document_id]
    return snapshot.payload if hasattr(snapshot, "payload") else snapshot


def _legacy_setting_name(name):
    if name == "analysis_scope_rules":
        return "LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE"
    return f"LOCAL_BUSINESS_ANALYTICS_{name.upper()}_FILE"


def get_document_specs():
    result = []
    for name, validator in _VALIDATORS.items():
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
                # Static documents have no legacy settings API.  The file
                # names remain available only to explicit test fixtures in
                # ``get_analytics_document_payload``.
                legacy_settings_path=None,
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
