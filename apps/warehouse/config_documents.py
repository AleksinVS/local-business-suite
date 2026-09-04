from apps.settings_center.document_specs import ConfigDocumentSpec
from apps.warehouse.contracts import validate_warehouse_settings_payload


def get_document_specs():
    return [
        ConfigDocumentSpec(
            document_id="warehouse.settings",
            domain="warehouse",
            storage_policy="database_override",
            default_path="contracts/warehouse/settings.json",
            schema_version=1,
            validator=validate_warehouse_settings_payload,
            failure_policy="visible_default_fallback",
            write_policy="editable",
            required_permission="manage_settings",
            owner="warehouse",
            legacy_settings_path="LOCAL_BUSINESS_WAREHOUSE_SETTINGS_FILE",
            consumer_classes=("warehouse",),
        )
    ]
