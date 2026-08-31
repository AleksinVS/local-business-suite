from apps.core.contracts import validate_integration_registry_payload
from apps.settings_center.document_specs import ConfigDocumentSpec


def get_document_specs():
    return [
        ConfigDocumentSpec(
            document_id="core.integration.registry",
            domain="core",
            storage_policy="git_static",
            default_path="contracts/integrations/registry.json",
            schema_version=1,
            validator=validate_integration_registry_payload,
            failure_policy="fail_closed",
            write_policy="read_only",
            required_permission="manage_settings",
            owner="core",
            legacy_settings_path="LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE",
            delivery_scope="django",
            consumer_classes=("integrations",),
            active_backend="git",
        )
    ]
